from .exporters import (
    build_text_download_href,
    normalize_output_filename,
    save_text_local,
    write_text_file,
)

import copy
import math
import re
import time
from datetime import datetime
from io import StringIO
from pathlib import Path, PurePosixPath

from ipywidgets import (
    FloatText,
    IntText,
    VBox,
    HBox,
    Box,
    Layout,
    Textarea,
    Button,
    Label,
    Dropdown,
    Text,
    Checkbox,
    HTML,
    Tab,
    Output,
)
from ipycanvas import Canvas
from IPython.display import display, FileLink

from .resource_manager import (
    list_resource_names,
    read_resource_text,
    resource_exists,
)

VERSION = "0.1.0"

# -----------------------
# Internal model
# -----------------------
WIDTH_STEP = 10
HEIGHT_STEP = 10
MIN_WIDTH = 10
MIN_HEIGHT = -40
DEFAULT_HEIGHT = 60
timeline_scale = 5

# Timeline positions
timeline_positions = {"f1": 150, "f2": 250, "Gz": 350}

class SequenceElement:
    def __init__(self, kind, file_path, start, duration, channel="f1",
                 title=None, name=None, definition="", power=None, phase=None, shape=None):
        
        self.kind = kind
        self.file_path = file_path
        self.start = start
        self.duration = duration
        self.channel = channel
        self.title = title or ""
        self.name = name or ""
        self.definition = definition
        self.power = power
        self.phase = phase
        self.shape = shape
        self.visual_width = self.duration * timeline_scale
                
        if self.kind == "flag":
            self.duration = 0
            self.visual_width = 30
            self.visual_height = 120
            self.flag_number = None
            
        elif self.kind == "delay":
            self.visual_height = 20
            self.visual_width = self.duration * timeline_scale
            self.manual = False
            
        else:
            if self.kind == "block":
                self.visual_height = DEFAULT_HEIGHT / 2
            else:
                self.visual_height = DEFAULT_HEIGHT
                               
class PulseSequence:
    def __init__(self):
        self.elements = []
    def add(self, element):
        self.elements.append(element)
    def coherence_summary(self):
        return f"Total elements: {len(self.elements)}"

# -----------------------
# Helper functions
# -----------------------
DELAY_RESOURCE_ID = "internal/delay"


def resource_filename(resource_id: str) -> str:
    """Return the filename component of a packaged resource identifier."""
    normalized = str(resource_id).replace("\\", "/")
    return PurePosixPath(normalized).name


def resource_id_to_parts(resource_id: str) -> tuple[str, ...]:
    """Convert a slash-separated resource identifier to package path parts."""
    normalized = str(resource_id).replace("\\", "/").strip("/")
    return tuple(part for part in normalized.split("/") if part)


def read_pulse_duration(resource_id: str) -> float:
    """Read an element duration from a packaged text resource."""
    if resource_id == DELAY_RESOURCE_ID:
        return 10.0

    try:
        resource_text = read_resource_text(*resource_id_to_parts(resource_id))
        for line in resource_text.splitlines():
            if "duration" in line:
                return float(line.split("=", 1)[1].strip())
    except (FileNotFoundError, ValueError, IndexError):
        pass

    return 10.0

def apply_placement_defaults(el: 'SequenceElement'):
    """
    Apply default name/definition/shape rules when placing a new element.
    - sp1.txt -> name p11, shape sp1 (any channel, for pulse or shaped)
    - grad    -> name p16, shape gp1
    - pulses: p0/p90/p180 rules per channel (as before)
    """
    base = resource_filename(el.file_path).lower()
    kind = (el.kind or "").lower()
    ch   = (el.channel or "").lower()

    # 1) Shaped/pulse file: sp1.txt
    if base == "sp1.txt":
        el.name = "p11"
        el.shape = "sp1"
        el.phase = "ph11"
        el.power = "pl0"
        return

    # 2) Gradients: fixed defaults
    if kind == "grad":
        el.name = "p16"
        el.shape = "gp1"
        el.channel = "Gz"
        el.power = "0"
        el.phase = ""
        return

    # 3) Pulse rules (channel-sensitive)
    if kind == "pulse":
        el.phase = "ph1" # default phase for all pulses
        
        if base == "p0.txt":
            el.name = "p0"
        elif base == "p90.txt":
            if ch == "f1":
                el.name = "p1"
                el.power = "pl1"
            elif ch == "f2":
                el.name = "p3"
                el.power = "pl2"
        elif base == "p180.txt":
            if ch == "f1":
                el.name = "p2"
                el.definition = "p1*2"  # derived from p1
                el.power = "pl1"
            elif ch == "f2":
                el.name = "p4"
                el.definition = "p3*2"  # derived from p3
                el.power = "pl2"
            
def pulse_fill_color(el):
    name = resource_filename(el.file_path).lower()
    if "p90" in name:
        return "white"
    elif "p180" in name:
        return "black"
    elif "p0" in name:
        return "lightgrey"
    else:
        return "white"

allowed_channels = {
    "pulse": ["f1", "f2"],
    "shaped": ["f1", "f2"],
    "block": ["f1", "f2"],
    "flag": ["f1", "f2"],
    "grad": ["Gz"]
}

drag_start_y = 0

def get_nearest_channel(y, kind=None):
    candidates = timeline_positions
    if kind in allowed_channels:
        # Only channels allowed for this kind
        candidates = {ch: timeline_positions[ch] for ch in allowed_channels[kind]}
    
    distances = {ch: abs(y - pos) for ch, pos in candidates.items()}
    return min(distances, key=distances.get)

def renumber_delays():
    delays = sorted(
        [el for el in sequence.elements if el.kind == "delay"],
        key=lambda e: e.start
    )

    counter = 1
    for el in delays:
        if not el.name:   # only auto-name if empty
            if counter == 1:
                el.name = "d1"
            else:
                el.name = f"d{19 + counter - 1}"
        counter += 1

def has_channel_time_conflict(channel, new_start, new_duration, ignore_el=None):
    new_end = new_start + new_duration

    for el in sequence.elements:
        if el == ignore_el:
            continue
        if el.kind in ["delay", "flag"]:
            continue
        if el.channel != channel:
            continue

        el_end = el.start + el.duration

        if not (new_end <= el.start or new_start >= el_end):
            return True

    return False
def remove_overlapping_delays():
    """
    Hard fix: if two delays occupy the same region,
    keep the first and delete the others.
    """
    delays = [el for el in sequence.elements if el.kind == "delay"]
    delays.sort(key=lambda e: e.start)

    cleaned = []
    
    for d in delays:
        overlap = False
        
        for c in cleaned:
            c_end = c.start + c.duration
            d_end = d.start + d.duration
            
            if not (d_end <= c.start or d.start >= c_end):
                overlap = True
                
                # Prefer manual delays over automatic ones
                if getattr(d, "manual", False) and not getattr(c, "manual", False):
                    sequence.elements.remove(c)
                    cleaned.remove(c)
                    cleaned.append(d)
                else:
                    if d in sequence.elements:
                        sequence.elements.remove(d)
                break
        
        if not overlap:
            cleaned.append(d)
            
def rebuild_global_delays():

    old_delays = sorted(
    [el for el in sequence.elements if el.kind == "delay"],
    key=lambda e: (not getattr(e, "manual", False), e.start)
    )
    
    sequence.elements = [
        el for el in sequence.elements
        if el.kind != "delay" or getattr(el, "manual", False)
    ]

    dash_x = 40 / timeline_scale
    fid_start_time = (canvas.width - 83) / timeline_scale
    delay_file = DELAY_RESOURCE_ID

    def create_delay(start, duration):

        for old in old_delays:
        
            old_end = old.start + old.duration
            new_end = start + duration
        
            # If delay overlaps the new region, reuse it
            if not (new_end <= old.start or start >= old_end):
        
                old.start = start
                old.duration = duration
                old.visual_width = duration * timeline_scale
        
                sequence.add(old)
                return

        # Otherwise create a new automatic delay
        new_delay = SequenceElement(
            kind="delay",
            file_path=delay_file,
            start=start,
            duration=duration,
            channel="f1",
            name=""
        )

        new_delay.manual = False
        sequence.add(new_delay)

    pulses = sorted(
        [el for el in sequence.elements
         if el.kind in ["pulse", "block", "grad", "shaped", "flag"]],
        key=lambda e: e.start
    )

    current_time = dash_x

    for pulse in pulses:
        if pulse.start > current_time:
            create_delay(current_time, pulse.start - current_time)

        current_time = max(current_time, pulse.start + pulse.duration)

    if current_time < fid_start_time:
        create_delay(current_time, fid_start_time - current_time)

    remove_overlapping_delays()
    renumber_delays()    

# -----------------------
# Program state
# -----------------------
sequence = PulseSequence()
selected_element = {"kind": None, "file_path": None}
history = []

dragging_el = None
drag_mode = None
drag_start_x = 0
drag_initial_width = 0
drag_initial_height = 0
drag_start_time = 0

# -----------------------
# Buttons / UI Controls
# -----------------------

def save_state():
    history.append(copy.deepcopy(sequence))
def refresh_ui():
    draw_sequence()
    coherence_label.value = sequence.coherence_summary()

allow_delay_selection = False

# -----------------------
# Button Handlers
# -----------------------

def toggle_delay_selection(b):
    global allow_delay_selection

    allow_delay_selection = not allow_delay_selection
    b.description = (
        "Delay ON"
        if allow_delay_selection
        else "Delay OFF"
    )

    b.button_style = (
        "success"
        if allow_delay_selection
        else "info"
    )


def undo_last(b):
    global sequence
    if not history:
        return

    sequence = history.pop()
    refresh_ui()

def clear_sequence(b):

    save_state()
    sequence.elements.clear()

    dash_x = 40 / timeline_scale
    fid_start_time = (canvas.width - 83) / timeline_scale
    delay_file = DELAY_RESOURCE_ID

    delay = SequenceElement(
        kind="delay",
        file_path=delay_file,
        start=dash_x,
        duration=fid_start_time - dash_x,
        channel="f1",
        name="d1"
    )

    sequence.add(delay)

    refresh_ui()

def delete_selected_element(b):
    global current_element
    if current_element is None:
        print("No element selected.")
        return

    if current_element in sequence.elements:
        save_state()  # add to undo history
        sequence.elements.remove(current_element)
        rebuild_global_delays()
        renumber_delays()
        draw_sequence()
        coherence_label.value = sequence.coherence_summary()
        print(f"Deleted element: {current_element.name}")

    current_element = None
    
# -----------------------
# Button Creation
# -----------------------

toggle_delays_btn = Button(
    description="Delay Selection",
    button_style="info",
    tooltip="Click to allow selecting delay elements",
    layout=Layout(width="200px")
)

undo_button = Button(
    description="Undo"
)

clear_button = Button(
    description="Clear"
)

print_names_button = Button(
    description="Generate",
    button_style="primary"
)

delete_button = Button(
    description="Delete",
    button_style="danger",
    tooltip="Delete selected element"
)

phase_cycle_checkbox = Checkbox(
    value=False,
    description="phase table",
    indent=False
)

export_btn = Button(
    description="Export Canvas",
    button_style="warning",   # yellow/orange
    layout=Layout(width="200px")
)

# Visible status area for generation success and errors.
generation_output = Output(
    layout=Layout(
        border="1px solid #d9d9d9",
        padding="6px",
        width="100%",
        display="none",
    )
)

browser_download_button = Button(
    description="Generate",
    tooltip="Prepare the pulse program for browser download",
    button_style="primary"
)

browser_download_link = HTML(
    value="",
)

def export_png(b):

    # redraw everything
    draw_sequence()

    # force pixel sync from browser
    canvas.sync_image_data = True
    canvas.flush()

    # allow browser time to finish rendering
    time.sleep(0.15)

    filename = f"{exp_title.value or 'sequence'}.png"

    canvas.to_file(filename)

    canvas.sync_image_data = False

    print("Saved:", filename)
    
export_btn.on_click(export_png)

# -----------------------
# Main Pulse Program Generator
# -----------------------

cpd_pulses = set()
cpd_delays = set()
cpd_powers = set()
cpd_phases = set()
cpd_shapes = set()

def build_pulse_program_text(include_phase_cycle: bool = False) -> str:
    """Build and return the Bruker pulse-program text."""
    # Clear previous
    cpd_pulses.clear()
    cpd_delays.clear()
    cpd_powers.clear()
    cpd_phases.clear()
    cpd_shapes.clear()

    f = StringIO()


    # -----------------------
    # Header section
    # -----------------------
    f.write(f";{exp_title.value}\n")
    f.write(f";avance-version ({datetime.now().strftime('%Y-%m-%d')})\n")
    f.write(f";{exp_comment.value}\n")
    f.write(";\n")
    f.write(f";$CLASS={exp_class.value}\n")
    f.write(f";$DIM={exp_dim.value}\n")
    f.write(f";$TYPE={exp_type.value}\n")
    f.write(f";$SUBTYPE={exp_subtype.value}\n")
    f.write(f";$COMMENT={exp_comment.value}\n\n")

    # -----------------------
    # Include files
    # -----------------------
    f.write("#include <Avance.incl>\n")

    if any(el.kind.lower() == "grad" for el in sequence.elements):
        f.write("#include <Grad.incl>\n")

    delay_keywords = ["delta", "tau", "Delta", "Tau", "epsilon"]
    if any(
        el.kind.lower() == "delay" and el.name
        for el in sequence.elements
        if any(k in el.name for k in delay_keywords)
    ):
        f.write("#include <Delay.incl>\n")

    if exp_incl.value.strip():
        f.write(f"#include <{exp_incl.value.strip()}>\n")

    f.write("\n")
    # -----------------------
    # 2D acquisition parameters
    # -----------------------
    if exp_dim.value == "2D" and exp_2d_option.value != "undefined":
        f.write('"d0=3u"\n')
        f.write('"in0=inf1/2"\n\n')
        
    # -----------------------
    # Pulse / delay definitions
    # -----------------------
    pulses_written = set()
    delays_written = set()

    for el in sequence.elements:

        desc = el.definition.strip()
    
        if el.kind.lower() in ["pulse", "block", "shaped"]:

            if desc and el.name not in pulses_written:
                f.write(f'"{el.name}={desc}"\n')
                pulses_written.add(el.name)

        elif el.kind.lower() == "delay":

            if desc and el.name not in delays_written:
                f.write(f'"{el.name}={desc}"\n')
                delays_written.add(el.name)

    f.write("\n")

    # -----------------------
    # vdlist logic
    # -----------------------

    vdlist_used = any(
    el.kind.lower() == "delay" and getattr(el, "name", "").lower() == "vd"
    for el in sequence.elements
    )
    
    if vdlist_used:
        f.write("define list<delay> vd=<$VDLIST>\n")
        f.write("\n")

    # -----------------------
    # vclist logic
    # -----------------------
    vclist_used = any(
        el.kind.lower() == "flag"
        and re.fullmatch(r"lo\s+to\s+\d+\s+times\s+vclist", getattr(el, "definition", "").lower().strip())
        for el in sequence.elements
    )
    
    if vclist_used:
        f.write("define list<loopcounter> vc=<$VCLIST>\n")
        f.write("\n")
        
    # -----------------------
    # c logic
    # -----------------------
    clogic_used = any(
        el.kind.lower() == "flag"
        and re.fullmatch(r"lo\s+to\s+\d+\s+times\s+c", getattr(el, "definition", "").lower().strip())
        for el in sequence.elements
    )
    
    # -----------------------
    # ACQT0 correction if last element is a pulse
    # -----------------------
    if sequence.elements:
        last_el = sequence.elements[-1]
    
        if last_el.kind.strip().lower() in ["pulse", "shaped"]:
            p_var = last_el.name
    
            if p_var == "p1":
                f.write("acqt0=-p1*2/3.1416\n\n")
            else:
                f.write(f"acqt0=-tan(({p_var}/p1)*(PI/4))*p1*2/3.1416\n\n")
                f.write("\n")
    
    # -----------------------
    # Pulse program body
    # -----------------------
    def write_flag(el):
    
        number = getattr(el, "flag_number", None)
    
        if number is None:
            number_text = "<flag>"
        else:
            number_text = str(number)
    
        desc = (el.definition or "").strip()
    
        if desc:
            return f"{number_text} {desc}"        
        return number_text
    
    def write_delay(el):
        return f" {el.name}"

    ea_gradients = {
    dd.value for dd in shape_dropdowns
    if dd.value
    }

    ea_map = {}

    if exp_2d_option.value == "Echo-Antiecho":
        selected_gp = [dd.value for dd in shape_dropdowns if dd.value]
        ea_map = {
            gp: f"EA{i}"
            for i, gp in enumerate(selected_gp, start=1)
        }

    def write_grad(el):
    
        gradients = sorted(
            [g for g in sequence.elements if g.kind.lower() == "grad"],
            key=lambda g: g.start
        )
    
        gp = f"gp{gradients.index(el)+1}"
    
        if gp in ea_map:
            gp += f"*{ea_map[gp]}"
    
        return f" {el.name}:{gp}\n d16"
        
    def write_block(el):
    
        title = el.title.strip().lower()
        channel = el.channel.strip().lower()
    
        cpd_filename = f"{title}_{channel}.txt"

        if resource_exists("cpdlib", cpd_filename):
            text = read_resource_text("cpdlib", cpd_filename)

    
            # extract parameters
            cpd_pulses.update(re.findall(r"\bp\d+\b", text))
            cpd_delays.update(re.findall(r"\bd\d+\b", text))
            cpd_powers.update(re.findall(r"\bpl\d+\b", text))
            cpd_phases.update(re.findall(r"\bph\d+\b", text))
            cpd_shapes.update(re.findall(r":([A-Za-z0-9_]+)", text))        
            return text.strip()
    
        if channel == "f2":
            text = "\n".join([
                " 4u pl13",
                " d19 cpd2:f2",
                " 4u do:f2",
                " 4u pl2:f2"
            ])
    
        elif channel == "f1":
            text = "\n".join([
                " 4u pl9",
                " d19 cpd1:f1",
                " 4u do:f1",
                " 4u pl1:f1"
            ])
    
        else:
            return f"; unknown block channel {channel}"
    
        # also parse fallback
        cpd_delays.update(re.findall(r"\bd\d+\b", text))
        cpd_powers.update(re.findall(r"\bpl\d+\b", text))
    
        return text
    
    def write_shaped(el):
        return f" ({el.name}:{el.shape} {el.phase}):{el.channel}"
        
    def write_pulse(el):
        return f" ({el.name} {el.phase}):{el.channel}"
    
    
    def write_center_element(el):
    
        kind = el.kind.lower()
    
        if kind == "pulse":
            return f"({el.name} {el.phase}):{el.channel}"
    
        if kind == "shaped":
            return f"({el.name}:{el.shape} {el.phase}):{el.channel}"
    
        if kind == "delay":
            return f"({el.name})"
    
        return None
        
    # -----------------------
    # Element dictionary
    # -----------------------        
    ELEMENT_WRITERS = {
        "flag": write_flag,
        "delay": write_delay,
        "grad": write_grad,
        "block": write_block,
        "shaped": write_shaped,
        "pulse": write_pulse,
        "flag": write_flag
    }
    
    elements_by_start = {}

    # -----------------------
    # Pulse sequence
    # -----------------------
    
    f.write("1 ze\n")
    f.write("2 30m pl1:f1\n")
    fid_start = get_fid_start_time()
    
    block_overlaps_fid = any(
        el.kind.lower() == "block" and
        (el.start + el.duration) >= fid_start
        for el in sequence.elements
    )
    
    if block_overlaps_fid:
        f.write(" 30m do:f2\n")
        
    if any(el.kind.lower() == "grad" for el in sequence.elements):
        f.write(" 30m UNBLKGRAD\n")

    if any(el.channel.lower() == "f2" for el in sequence.elements):
        f.write(" 30m pl2:f2\n")
    
    # group elements by start time
    for el in sequence.elements:
        start_key = round(el.start, 6)
        elements_by_start.setdefault(start_key, []).append(el)
    
    # write elements in chronological order
    for start in sorted(elements_by_start.keys()):
    
        els = elements_by_start[start]
    
        # remove blocks that start after the FID
        els = [
            e for e in els
            if not (e.kind.lower() == "block" and e.start >= fid_start)
        ]
    
        if not els:
            continue
    
        # -----------------------
        # single element
        # -----------------------
        if len(els) == 1:
        
            el = els[0]
            kind = el.kind.lower()
        
            # Skip blocks starting after FID
            if kind == "block" and el.start >= fid_start:
                continue
        
            writer = ELEMENT_WRITERS.get(kind)
        
            if writer:
                f.write(writer(el) + "\n")
            else:
                f.write(f"; unknown element type: {kind}\n")
        
        # -----------------------
        # multiple elements (centered elements)
        # -----------------------
          
        else:
        
            flags = [e for e in els if e.kind.lower() == "flag"]
            if flags:
                for e in flags:
                    f.write(write_flag(e) + "\n")
                continue
        
            center_parts = []
        
            for e in els:
                text = write_center_element(e)
                if text:
                    center_parts.append(text)
        
            if center_parts:
                line = " (center " + " ".join(center_parts) + " )"
                f.write(line + "\n")
            
    # -----------------------
    # Acquisition logic
    # -----------------------    
    if any(el.kind.lower() == "grad" for el in sequence.elements):
        f.write(" 4u BLKGRAD\n")

    # GO line
    if block_overlaps_fid:
        f.write(" 10u pl12:f2\n")
        f.write(" go=2 ph31 cpd2:f2\n")
    else:
        f.write(" go=2 ph31\n")
    
    # -----------------------
    # vdlist experiments
    # -----------------------    
    if vdlist_used:    
        f.write(" d11 wr #0 if #0 vd.inc\n")
        f.write(" lo to 1 times td1\n")
    
        if block_overlaps_fid:
            f.write(" d11 do:f2\n")
            
    # -----------------------
    # vclist experiments
    # -----------------------    
    elif vclist_used:    
        f.write(" d11 wr #0 if #0 vclist.inc\n")
        f.write(" lo to 1 times td1\n")
    
        if block_overlaps_fid:
            f.write(" d11 do:f2\n")
            
    # -----------------------
    # c logic
    # -----------------------    
    elif clogic_used:
        f.write(" d11 wr #0 if #0 ivc\n")
        f.write(" lo to 1 times td1\n")
    
        if block_overlaps_fid:
            f.write(" d11 do:f2\n")
        
    # -----------------------
    # Normal acquisition
    # -----------------------
    else:
    
        if exp_dim.value == "1D":
            f.write(" 30m mc #0 to 2 F0(zd)\n")
    
        else:
    
            if exp_2d_option.value != "undefined":
    
                phase_sensitive = ["States", "TPPI", "States-TPPI"]
    
                if exp_2d_option.value in phase_sensitive:
    
                    pulses = [dd.value for dd in pulse_dropdowns if dd.value]
    
                    calph_parts = [f"calph({p}, +90)" for p in pulses]
                    calph_string = " & ".join(calph_parts)
    
                    f.write(
                        f" 30m mc #0 to 2 "
                        f"F1PH({calph_string}, caldel(d0, +in0))\n"
                    )
    
                elif exp_2d_option.value == "Echo-Antiecho":
                    pulses = [dd.value for dd in pulse_dropdowns if dd.value]
    
                    calph_parts = [f"calph({p}, +90)" for p in pulses]
                    calph_string = " & ".join(calph_parts)
                    
                    selected_gp = [dd.value for dd in shape_dropdowns if dd.value]
    
                    # Map gp1 -> EA1, gp3 -> EA2, ...
                    ea_map = {
                        gp: f"EA{i}"
                        for i, gp in enumerate(selected_gp, start=1)
                    }
    
                    calea_string = " & ".join(
                        f"calgrad({ea})"
                        for ea in ea_map.values()
                    )
    
                    pulses = [dd.value for dd in pulse_dropdowns if dd.value]
                    calph_string = " & ".join(
                        f"calph({p}, +90)"
                        for p in pulses
                    )
    
                    args = [calea_string, "caldel(d0, +in0)"]
    
                    if calph_string:
                        args.append(calph_string)
    
                    f.write(
                        f" 30m mc #0 to 2 "
                        f"F1EA({'& '.join(args)})\n"
                    )
    
                else:
    
                    f.write(" 30m mc #0 to 2 F1QF(caldel(d0, +in0))\n")
    
        if block_overlaps_fid:
            f.write(" 30m do:f2\n")
    
    f.write("exit\n\n")    
    # -----------------------
    # Post pulse sequence entries (phase table and definitions)
    # -----------------------
    
    # -----------------------
    # Phase tables
    # -----------------------
    
    if phase_cycle_checkbox.value:
    
        f.write(phase_cycle_output.value + "\n\n")
    
    else:
    
        unique_phases = set()
    
        for el in sequence.elements:
            if el.phase:
                unique_phases.add(el.phase.strip())
    
        unique_phases |= cpd_phases
    
        for ph in sorted(unique_phases):
            f.write(f"{ph}=0\n")
    
        f.write("ph31=0\n\n")
        f.write("\n")
    
    # -----------------------
    # Power / Pulse / Delay / Shape Definitions
    # -----------------------
    def load_definitions(filename: str) -> dict[str, str]:
        """Load definition mappings from packaged resources."""
        try:
            definition_text = read_resource_text("defs", filename)
        except FileNotFoundError:
            return {}

        definitions: dict[str, str] = {}
        for line in definition_text.splitlines():
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                definitions[key.strip()] = value.strip()

        return definitions

    # Load definition dictionaries
    power_defs = load_definitions("power_def.txt")
    pulse_defs = load_definitions("pulse_def.txt")
    delay_defs = load_definitions("delay_def.txt")
    shape_defs = load_definitions("shaped_def.txt")
    
    # Collect unique identifiers from the sequence
    unique_power = sorted(
        {
            el.power.strip()
            for el in sequence.elements
            if el.power and re.match(r"^pl\d+$", el.power.strip(), re.IGNORECASE)
        } | {
            p for p in cpd_powers if re.match(r"^pl\d+$", p, re.IGNORECASE)
        }
    )
    
    unique_pulses = sorted({
        el.name.strip()
        for el in sequence.elements
        if el.kind.lower() in ["pulse", "shaped", "block"] and el.name.strip()
    } | {p for p in cpd_pulses if p})
    
    unique_delays = sorted(
        {el.name for el in sequence.elements if el.kind.lower() == "delay"}
        | cpd_delays
    )

    unique_shapes = sorted({
        el.shape.strip()
        for el in sequence.elements
        if getattr(el, "shape", None)
    } | cpd_shapes)
    
    for pl in unique_power:
        explanation = power_defs.get(pl, "undefined")
        f.write(f";{pl}: {explanation}\n")
    f.write("\n")
    
    shape_definitions = {}

    for el in sequence.elements:
        if getattr(el, "shape", None):
            s = el.shape.strip()
            if s not in shape_definitions and el.definition.strip():
                shape_definitions[s] = el.definition.strip()
                
    for s in unique_shapes:
        explanation = shape_defs.get(s, "undefined")
        f.write(f";{s}: {explanation}\n")
    
        definition = shape_definitions.get(s, "")
        if definition:
            num = re.search(r"\d+", s)
            if num:
                f.write(f";spnam{num.group()}: {definition}\n")
    
    for p in unique_pulses:
        explanation = pulse_defs.get(p, "undefined")
        f.write(f";{p}: {explanation}\n")
    f.write("\n")
    
    for d in unique_delays:
        explanation = delay_defs.get(d, "undefined")
        f.write(f";{d}: {explanation}\n")
    f.write("\n")

    # -----------------------
    # User scan parameters
    # -----------------------
    f.write(f";ns: {ns_text.value} * n, total number of scans: NS * TD0\n")
    f.write(f";ds: {ds_text.value}\n\n")

    if any((vdlist_used, vclist_used, clogic_used)):
        f.write(";td1: number of experiments in list\n")
            
    # -----------------------
    # 2D parameter explanation
    # -----------------------
    if exp_dim.value == "2D":
    
        if exp_2d_option.value == "undefined":
    
            f.write(";FnMODE: undefined\n\n")
    
        else:
    
            # automatically count delays named d0
            nd0 = sum(
                1 for el in sequence.elements
                if el.kind.lower() == "delay" and el.name.strip() == "d0"
            )
    
            f.write(";inf1: 1/SW(H) = 2 * DW(H)\n")
            f.write(";in0: 1/(2 * SW(H)) = DW(H)\n")
            f.write(f";nd0: {nd0}\n")
            f.write(";td1: number of experiments\n\n")
    
            f.write(f";FnMODE: {exp_2d_option.value}\n\n")
    # -----------------------
    # CPD related logic
    # -----------------------
    block_overlaps_fid = any(
        el.kind.lower() == "block" and
        (el.start + el.duration) >= fid_start
        for el in sequence.elements
    )
    
    if block_overlaps_fid:
        f.write(";cpd2: decoupling according to sequence defined by cpdprg2\n")
        f.write(";pcpd2: f2 channel - 90 degree pulse for decoupling sequence\n")
    else:
        f.write(";\n")
        
    # -----------------------
    # Gradient related logic
    # -----------------------
    gradients = sorted(
        [el for el in sequence.elements if el.kind.lower() == "grad"],
        key=lambda e: e.start
    )
    
    # Renumber gradient shapes
    for i, el in enumerate(gradients, start=1):
        el.shape = f"gp{i}"
    
    if gradients:
    
        f.write(";for z-only gradients:\n")
    
        for i, el in enumerate(gradients, start=1):
    
            power = el.power
    
            if not power:
                power_str = "undefined"
            else:
                power_str = f"{power}".rstrip("%") + "%"
    
            f.write(f";gpz{i}: {power_str}\n")
    
        f.write("\n;use gradient files:\n")
    
        for i, el in enumerate(gradients, start=1):
            f.write(f";gpnam{i}: {el.title}\n")
    
        f.write("\n")
    
    # -----------------------
    # Footer
    # -----------------------
    f.write(";$Id: Generated using NMRpaintv0.1.0$\n")

    return f.getvalue()


def save_pulse_program(
    filename: str | Path,
    content: str,
) -> Path:
    """Save pulse-program text to an explicit local path."""
    return write_text_file(
        path=filename,
        content=content,
    )


def generate_pulse_program(
    filename: str | Path,
    include_phase_cycle: bool = False,
) -> Path:
    """Build and save a pulse program while preserving the existing GUI API."""

    content = build_pulse_program_text(
        include_phase_cycle=include_phase_cycle,
    )

    return save_pulse_program(
        filename=filename,
        content=content,
    )


def _generate_local_pulse_program() -> Path:
    """Build and save the current pulse program locally."""
    filename = normalize_output_filename(
        exp_title.value,
        default="pulse_program",
    )

    return save_text_local(
        content=content,
        filename=filename,
    )


def generate_program_button_click(b):
    """Generate the current pulse program in the local output directory."""
    generation_output.layout.display = "block"
    generation_output.clear_output(wait=True)

    with generation_output:
        try:
            output_path = _generate_local_pulse_program()
            print(f"Pulse program saved to: {output_path.resolve()}")
        except Exception as exc:
            print(f"Generation failed: {type(exc).__name__}: {exc}")


def generate_and_phase(b):
    """Populate phase rows, generate the phase cycle, and save locally."""
    generation_output.layout.display = "block"
    generation_output.clear_output(wait=True)
    browser_download_link.value = ""

    with generation_output:
        try:
            populate_phase_rows()

            if phase_cycle_checkbox.value:
                generate_phase_cycle()

            output_path = _generate_local_pulse_program()
            print(f"Pulse program saved to: {output_path.resolve()}")
        except Exception as exc:
            print(f"Generation failed: {type(exc).__name__}: {exc}")

def prepare_browser_download(b):

    populate_phase_rows()

    if phase_cycle_checkbox.value:
        generate_phase_cycle()

    content = build_pulse_program_text()

    filename = normalize_output_filename(
        exp_title.value,
        default="pulse_program",
    )

    href = build_text_download_href(content)

    browser_download_link.value = f"""
    <a id="nmrpaint_download"
       href="{href}"
       download="{filename}">
       Download
    </a>
    """

# -----------------------
# Phase Cycle GUI
# -----------------------

phase_rows = []

PHASE_MAP = {
    "x":0,
    "y":1,
    "-x":2,
    "-y":3
}

phase_cycle_header = HBox([
    Label("pulse:phase", layout=Layout(width="120px")),
    Label("nominal phase", layout=Layout(width="120px")),
    HTML("Δ<i>p</i>", layout=Layout(width="100px")),
    HTML("disallowed Δ<i>p</i>", layout=Layout(width="150px"))
])

phase_cycle_container = VBox([])
phase_cycle_output = Textarea(
    layout=Layout(width="436px", height="160px")
)

def add_phase_row(pulse, phase):

    nominal = Dropdown(
        options=["x","y","-x","-y"],
        value="x",
        layout=Layout(width="120px")
    )

    delta = Text(
        value="0",
        layout=Layout(width="100px")
    )

    disallowed = Text(
        value="",
        layout=Layout(width="150px")
    )

    label = Label(f"{pulse}:{phase}", layout=Layout(width="120px"))

    row_widget = HBox([label, nominal, delta, disallowed])

    phase_rows.append({
        "pulse":pulse,
        "phase":phase,
        "nominal":nominal,
        "delta":delta,
        "disallowed":disallowed
    })

    phase_cycle_container.children = list(phase_cycle_container.children) + [row_widget]

phase_cycle_box = VBox([
    HTML("""
    <div style="
        text-align:center;
        font-size:15px;
        font-weight:bold;
    ">
        Phase Cycle Generator
    </div>
    """),
    phase_cycle_header,
    phase_cycle_container,
    phase_cycle_output
])

phase_cycle_box.layout = Layout(width="440px")

def populate_phase_rows():

    existing = {row["phase"] for row in phase_rows}

    for el in sequence.elements:

        if el.phase and el.phase.startswith("ph"):

            if el.phase not in existing:

                add_phase_row(el.name, el.phase)
                
import itertools

def determine_steps(delta, disallowed):

    delta = int(delta)

    if disallowed is None or disallowed.strip() == "":
        return [0,2]

    disallowed = int(disallowed)

    diff = disallowed - delta

    print("delta =", delta)
    print("disallowed =", disallowed)
    print("difference =", diff)

    if diff % 2 == 0:
        print("Using 4-step cycle")
        return [0,1,2,3]

    print("Using 2-step cycle")
    return [0,2]
    
def nested_cycles(bases):

    lengths = [len(b) for b in bases]

    total_steps = 1
    for l in lengths:
        total_steps *= l

    cycles = []

    repeat_block = total_steps

    for base in bases:

        L = len(base)
        repeat_block //= L

        row = []

        for v in base:
            row += [v] * repeat_block

        row = row * (total_steps // len(row))

        cycles.append(row)

    return cycles
    
def generate_phase_cycle():

    print("generate_phase_cycle() called")

    active = []
    inactive = []
    
    for r in phase_rows:

        delta = int(r["delta"].value)

        row = {
            "phase": r["phase"],
            "delta": delta,
            "nominal": PHASE_MAP[r["nominal"].value],
            "disallowed": r["disallowed"].value.strip()
        }

        if delta != 0:
            active.append(row)
        else:
            inactive.append(row)

    # sort phases numerically (ph1, ph2, ph3, ...)
    active.sort(key=lambda r: int(r["phase"][2:]))
    inactive.sort(key=lambda r: int(r["phase"][2:]))
    
    if not active:
        phase_cycle_output.value = "No active phase cycles"
        return

    # ---- determine steps for each phase
    bases = [determine_steps(r["delta"], r["disallowed"]) for r in active]
    
    print("base_steps per phase =", bases)
    
    # ---- nested cycles
    cycles = nested_cycles(bases)
    
    tableA = {}
    for i,row in enumerate(active):
        tableA[row["phase"]] = cycles[i]
    
    cols = len(cycles[0])
    
    # ---- Table B (receiver)
    ph31 = []

    for c in range(cols):

        s = 0

        for r,row in enumerate(active):
            s += cycles[r][c] * row["delta"]

        ph31.append(s % 4)

    # ---- Table C
    tableC = {}

    # active phases
    for r,row in enumerate(active):

        vals = tableA[row["phase"]]
        nominal = row["nominal"]

        tableC[row["phase"]] = [(v + nominal) % 4 for v in vals]

    # inactive phases (Δp = 0)
    for row in inactive:

        nominal = row["nominal"]
        tableC[row["phase"]] = [nominal] * cols

    # ---- Print result
    text = ";Phase table\n"

    for ph in sorted(tableC.keys(), key=lambda x: int(x[2:])):
        v = tableC[ph]
        text += f"{ph}={' '.join(map(str,v))}\n"
    text += "\nph31=" + " ".join(map(str,ph31))

    phase_cycle_output.value = text
    
# -----------------------
# Register Handlers
# -----------------------

toggle_delays_btn.on_click(toggle_delay_selection)
undo_button.on_click(undo_last)
clear_button.on_click(clear_sequence)
delete_button.on_click(delete_selected_element)

print_names_button._click_handlers.callbacks.clear()
print_names_button.on_click(generate_and_phase)

browser_download_button._click_handlers.callbacks.clear()
browser_download_button.on_click(prepare_browser_download)

# Number of scans (ns) and dummy scans (ds)
ns_text = IntText(
    description="ns:",
    value=1,
    layout=Layout(width="100px"),
    style={'description_width': '30px'}
)

ds_text = IntText(
    description="ds:",
    value=0,
    layout=Layout(width="100px"),
    style={'description_width': '30px'}
)

# -----------------------
# Experiment Properties Row
# -----------------------
exp_title = Text(
    description="Title:",
    layout=Layout(width="200px", margin="0px"),
    style={'description_width': '70px'}
)

exp_class = Dropdown(
    description="Class:",
    options=["HighRes", "HighRes HWT", "HighRes Incl"],
    value="HighRes",
    layout=Layout(width="160px"),  # total width
    style={'description_width': '40px'}  # label width
)

exp_dim = Dropdown(
    description="Dim:",
    options=["1D", "2D"],
    value="1D",
    layout=Layout(width="110px"),
    style={'description_width': '30px'}  # label width
)

exp_2d_option = Dropdown(
    description="2D Option:",
    options=["States-TPPI", "QF", "Echo-Antiecho", "QF(no frequency)", "undefined", "States", "TPPI"],
    value=None,
    layout=Layout(width="200px")
)
exp_2d_option.layout.display = "none"

#pulses
pulse_dropdowns = []
pulse_section_label = Label("Incr pulse:", layout=Layout(width="80px"))

pulse_dropdowns_container = HBox([], layout=Layout(width="200px", spacing="2px", align_items="center", margin="0px", padding="0px"))
pulse_section = HBox(
    [pulse_section_label, pulse_dropdowns_container],
    layout=Layout(spacing="2px", align_items="center", margin="0px", padding="0px", display="none")
)

#shapes
shape_dropdowns = []
shape_section_label = Label("EA grad:", layout=Layout(width="80px"))
shape_dropdowns_container = HBox([], layout=Layout(width="200px", spacing="2px", align_items="center", margin="0px", padding="0px"))
shape_section = HBox(
    [shape_section_label, shape_dropdowns_container],
    layout=Layout(spacing="2px", align_items="center", margin="0px", padding="0px", display="none")
)

def update_2d_dropdowns(change=None):

    phase_sensitive = ["States", "TPPI", "States-TPPI"]

    # ---- Echo-Antiecho case ----
    if exp_2d_option.value == "Echo-Antiecho":
    
        pulse_section.layout.display = "flex"
        shape_section.layout.display = "flex"
    
        gradients = sorted(
            [el for el in sequence.elements if el.kind.lower() == "grad"],
            key=lambda el: el.start
        )
    
        shape_names = [f"gp{i}" for i in range(1, len(gradients) + 1)]
    
        shape_dropdowns.clear()
        shape_dropdowns_container.children = ()
    
        def add_dropdown(change=None):
            if change is not None and not change["new"]:
                return
    
            dd = Dropdown(
                options=[""] + shape_names,
                description="",
                layout=Layout(width="140px")
            )
    
            dd.observe(add_dropdown, names="value")
    
            shape_dropdowns.append(dd)
            shape_dropdowns_container.children = tuple(shape_dropdowns)
    
        add_dropdown()
        return

    # ---- Phase-sensitive experiments ----
    if exp_2d_option.value not in phase_sensitive:
        pulse_section.layout.display = "none"
        shape_section.layout.display = "none"

        pulse_dropdowns.clear()
        pulse_dropdowns_container.children = ()
        return


    pulse_section.layout.display = "flex"
    shape_section.layout.display = "none"

    # get available pulses
    pulse_names = sorted({el.phase for el in sequence.elements
                          if el.kind.lower() in ["pulse", "shaped"]})

    if not pulse_names:
        return

    pulse_dropdowns.clear()
    pulse_dropdowns_container.children = ()

    def add_dropdown(change=None):
        if change is not None and not change["new"]:
            return

        dd = Dropdown(
            options=[""] + pulse_names,
            description="",
            layout=Layout(width="140px")
        )

        dd.observe(add_dropdown, names="value")

        pulse_dropdowns.append(dd)
        pulse_dropdowns_container.children = tuple(pulse_dropdowns)

    add_dropdown()

exp_2d_option.observe(update_2d_dropdowns, names="value")
update_2d_dropdowns()

exp_type = Dropdown(
    description="Type:",
    options=["", "relaxation", "DNP"],
    value="",
    layout=Layout(width="150px")
)

exp_subtype = Text(
    description="Subtype:",
    value="",
    layout=Layout(width="150px")
)

exp_incl = Text(
    description="Include:",
    value="",
    layout=Layout(width="150px")
)

exp_comment = Text(
    description="Comment:",
    value="",
    layout=Layout(width="300px")
)

def on_dim_change(change):
    if change['new'] == "2D":
        exp_2d_option.layout.display = "flex"
    else:
        exp_2d_option.layout.display = "none"

exp_dim.observe(on_dim_change, names='value')

# -----------------------
# Packaged element resources
# -----------------------

element_types = ["pulse", "shaped", "grad", "block", "flag"]
element_files: dict[str, list[str]] = {}


def load_element_files() -> None:
    """Load element resource identifiers from the installed package."""
    element_files.clear()

    for element_type in element_types:
        filenames = list_resource_names(
            "elements",
            element_type,
            suffix="",
        )
        element_files[element_type] = [
            f"elements/{element_type}/{filename}"
            for filename in filenames
        ]


load_element_files()

# -----------------------
# GUI Components
# -----------------------
property_editor_header = HTML("""
<div style="
    text-align:center;
    font-size:15px;
    font-weight:bold;
">
    Element editor
</div>
""")

property_editor_content = VBox(
    layout=Layout(width="100%")
)
property_editor_box = VBox(
    [
        property_editor_header,
        property_editor_content
    ],
    layout=Layout(
        width="230px",
        overflow="hidden"
    )
)

field_layout = Layout(width="210px")
label_style = {"description_width": "85px"}
button_layout = Layout(width="210px", margin="8px 0 0 0")

el_title = Text(
    description="Title",
    layout=field_layout,
    style=label_style
)

el_name = Text(
    description="Name",
    layout=field_layout,
    style=label_style
)

el_definition = Text(
    description="Definitions",
    layout=field_layout,
    style=label_style
)

el_shape = Text(
    description="Shape",
    layout=field_layout,
    style=label_style
)

el_channel = Dropdown(
    description="Channel",
    options=["f1", "f2", "Gz"],
    layout=field_layout,
    style=label_style
)

el_power = Text(
    description="Power",
    layout=field_layout,
    style=label_style
)

el_phase = Text(
    description="Phase",
    layout=field_layout,
    style=label_style
)

el_duration = FloatText(
    description="Duration",
    layout=field_layout,
    style=label_style
)

el_height = IntText(
    description="Height",
    layout=field_layout,
    style=label_style
)

update_button = Button(
    description="Update Element",
    button_style="success",
    layout=button_layout
)

# Initial contents shown when NMRpaint starts
property_editor_content.children = (
    el_title,
    el_name,
    el_definition,
    el_shape,
    el_channel,
    el_power,
    el_phase,
    el_duration,
    el_height,
    update_button
)

def _coerce_for_widget(widget, value, *, default=None, dropdown_options=None):
    """
    Coerces 'value' into something acceptable for the given ipywidget.

    - Text/Textarea -> str
    - (FloatText, IntText) -> number
    - Checkbox -> bool
    - Dropdown -> member of options (or fallback to default or first option)
    """
    from ipywidgets import Text, Textarea, FloatText, IntText, Checkbox, Dropdown

    # Text-like: ensure string (never None)
    if isinstance(widget, (Text, Textarea)):
        if value is None:
            return "" if default is None else str(default)
        return str(value)

    # Numeric: ensure number (FloatText/IntText)
    if isinstance(widget, (FloatText, IntText)):
        if value is None or (isinstance(value, str) and not value.strip()):
            return float(default) if default is not None else 0.0
        try:
            # keep ints as ints for IntText, floats for FloatText
            if isinstance(widget, IntText):
                return int(value)
            else:
                return float(value)
        except Exception:
            # bad input -> fallback
            return float(default) if default is not None and not isinstance(widget, IntText) else (
                int(default) if default is not None else (0 if isinstance(widget, IntText) else 0.0)
            )

    # Checkbox: ensure bool
    if isinstance(widget, Checkbox):
        return bool(value) if value is not None else bool(default) if default is not None else False

    # Dropdown: ensure a valid option
    if isinstance(widget, Dropdown):
        opts = list(dropdown_options) if dropdown_options is not None else list(widget.options)
        # Normalize (tuple of (label, value)) to raw values if needed
        def opt_values(options):
            vals = []
            for o in options:
                if isinstance(o, tuple) and len(o) == 2:
                    vals.append(o[1])
                else:
                    vals.append(o)
            return vals

        values = opt_values(opts)
        # If provided value is invalid, fallback to default or first option (or None if empty)
        chosen = value
        if chosen not in values:
            chosen = default if default in values else (values[0] if values else None)
        return chosen

    # Fallback: return value or default
    return value if value is not None else default
    
def show_property_editor(el: SequenceElement):
    global current_element
    current_element = el
    kind = el.kind.lower()
    kind = el.kind.lower()

    # ---------------------------
    # Populate widget values
    # ---------------------------

    el_title.value = getattr(el, "title", "") or ""
    el_name.value = getattr(el, "name", "") or ""
    el_definition.value = getattr(el, "definition", "") or ""
    el_shape.value = getattr(el, "shape", "") or ""

    el_channel.value = getattr(el, "channel", "f1") or "f1"

    el_power.value = getattr(el, "power", "") or ""
    el_phase.value = getattr(el, "phase", "") or ""

    el_duration.value = getattr(el, "duration", 0)

    if hasattr(el, "visual_height"):
        el_height.value = el.visual_height

    # ---------------------------
    # Build editor layout
    # ---------------------------

    if kind == "pulse":

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_channel,
            el_power,
            el_phase,
            el_duration,
            el_height,
            update_button
        ]

    elif kind == "shaped":

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_shape,
            el_channel,
            el_power,
            el_phase,
            el_duration,
            el_height,
            update_button
        ]

    elif kind == "grad":

        visible_widgets = [
            el_title,
            el_name,
            el_channel,
            el_power,
            el_duration,
            el_height,
            update_button
        ]

    elif kind == "cpd":

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_channel,
            el_power,
            el_duration,
            el_height,
            update_button
        ]

    elif kind == "flag":

        visible_widgets = [
            el_definition,
            update_button
        ]

    elif kind == "block":

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_channel,
            el_duration,
            el_height,
            update_button
        ]

    elif kind == "delay":

        visible_widgets = [
            el_name,
            el_definition,
            el_duration,
            update_button
        ]

    else:

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_channel,
            el_duration,
            update_button
        ]

    property_editor_content.children = tuple(visible_widgets)

    # ---------------------------
    # Update callback
    # ---------------------------

    def update_el(b):

        save_state()

        el.title = el_title.value
        el.name = el_name.value
        el.definition = el_definition.value

        el.duration = el_duration.value
        el.visual_width = el.duration * timeline_scale

        if kind != "flag":
            el.channel = el_channel.value

        if kind in ["pulse", "shaped", "grad", "cpd"]:
            el.power = el_power.value

        if kind in ["pulse", "shaped"]:
            el.phase = el_phase.value

        if kind == "shaped":
            el.shape = el_shape.value

        if kind in ["pulse", "shaped", "block", "grad"]:
            el.visual_height = el_height.value

        if kind == "delay":
            el.manual = True

        if el.kind != "delay":
            rebuild_global_delays()

        renumber_delays()
        draw_sequence()
        coherence_label.value = sequence.coherence_summary()

        populate_phase_rows()
        generate_phase_cycle()

    update_button._click_handlers.callbacks.clear()
    update_button.on_click(update_el)

# -----------------------
# Canvas Setup
# -----------------------

canvas_width = 970
canvas_height = 400

def get_fid_start_time():
    return (canvas.width - 83) / timeline_scale

# Main canvas
canvas = Canvas(
    width=canvas_width,
    height=canvas_height,
    sync_image_data=False
)

# Overlay canvas
dynamic_canvas = Canvas(
    width=canvas_width,
    height=canvas_height,
    sync_image_data=False
)

# Force widget wrappers to overlap
for c in (canvas, dynamic_canvas):
    c.layout.position = "absolute"
    c.layout.left = "0px"
    c.layout.top = "0px"
    c.layout.width = f"{canvas_width}px"
    c.layout.height = f"{canvas_height}px"

dynamic_canvas.layout.pointer_events = "none"
canvas.layout.border = "1px solid black"

canvas_container = Box(
    children=[canvas, dynamic_canvas],
    layout=Layout(
        position="relative",
        width=f"{canvas_width}px",
        height=f"{canvas_height}px",
        display="block",
        overflow="hidden",
    )
)

canvas_box = canvas_container

# -----------------------
# Canvas resizing utility
# -----------------------
def set_canvas_size(new_width: int, new_height: int = None):
    """
    Resize main and overlay canvases and their container, then redraw.
    """
    global canvas_width, canvas_height
    new_height = canvas_height

    new_width = max(200, int(new_width))
    new_height = max(200, int(new_height))

    canvas_width = new_width
    canvas_height = new_height

    canvas.width = canvas_width
    canvas.height = canvas_height
    
    dynamic_canvas.width = canvas_width
    dynamic_canvas.height = canvas_height
    
    for c in (canvas, dynamic_canvas):
        c.layout.width = f"{canvas_width}px"
        c.layout.height = f"{canvas_height}px"
    
    canvas_container.layout.width = f"{canvas_width}px"
    canvas_container.layout.height = f"{canvas_height}px"

    canvas_container.layout.min_width  = f"{canvas_width}px"
    canvas_container.layout.min_height = f"{canvas_height}px"

    canvas_container.layout.width  = f"{canvas_width}px"
    canvas_container.layout.height = f"{canvas_height}px"

    canvas_container.layout.overflow_x = "hidden"
    canvas_container.layout.overflow_y = "visible"
    canvas_container.layout.align_items = "center"
    canvas_container.layout.box_sizing = "border-box"
    
    rebuild_global_delays()
    draw_sequence()
    coherence_label.value = sequence.coherence_summary()
    

# -----------------------
# Element Button
# -----------------------
def draw_preview(preview_canvas, kind, file_path):

    preview_canvas.clear()

    # Create temporary element
    temp_el = SequenceElement(kind, file_path, start=0, duration=4)
    temp_el.channel = "f1"

    # Preview size tuning
    temp_el.visual_width = 15
    temp_el.visual_height = 55

    # Temporarily override timeline position so drawing centers vertically
    original_pos = timeline_positions.get("f1", 150)
    timeline_positions["f1"] = preview_canvas.height - 1

    # Temporarily override timeline scale so x=0 centers element
    original_scale = globals()["timeline_scale"]
    globals()["timeline_scale"] = 4

    # Center horizontally
    temp_el.start = (preview_canvas.width / timeline_scale) / 2 - temp_el.duration / 2

    draw_element(preview_canvas, temp_el)

    # Restore global settings
    timeline_positions["f1"] = original_pos
    globals()["timeline_scale"] = original_scale
    
def create_element_button(kind, file_path):

    base = resource_filename(file_path).lower()

    # --- Display names ---
    display_names = {
        "p0.txt": "var",
        "p90.txt": "90",
        "p180.txt": "180",
        "sp1.txt": "sp1",
        "grad.txt": "gp1",
        "cpd.txt": "CPD",
        "flag.txt": "flag"
    }

    name = display_names.get(base, base.replace(".txt",""))

    preview = Canvas(
        width=60,
        height=60,
        layout=Layout(
            width="60px",
            height="60px"
        )
    )
    
    draw_preview(preview, kind, file_path)

    # Click handler
    def on_click(x, y):
        selected_element["kind"] = kind
        selected_element["file_path"] = file_path

    preview.on_mouse_down(on_click)
    
    label = Label(
        name,
        layout=Layout(
            width="60px",
            display="flex",
            justify_content="center"
        )
    )
    
    return VBox(
        [preview, label],
        layout=Layout(
            width="60px",
            align_items="center",
            justify_content="center",
            margin="0px",
            padding="0px",
            overflow="hidden"
        )
    )
    
# -----------------------
# Drawing
# -----------------------
def draw_element(c, el, _ignored=None):
    timeline_y = timeline_positions.get(el.channel, 150)
    x = int(el.start * timeline_scale)
    width = int(el.visual_width)
    height = int(el.visual_height)
    top_y = int(timeline_y - height)

    # DELAY
    if el.kind == "delay":
    
        base_y = timeline_positions.get(el.channel or "f1", 150)
        timeline_y = base_y - 30
        
        start_x = el.start * timeline_scale
        end_x   = (el.start + el.duration) * timeline_scale
    
        c.stroke_style = "black"
        c.line_width = 2
    
        # Horizontal line
        c.begin_path()
        c.move_to(start_x, timeline_y)
        c.line_to(end_x, timeline_y)
        c.stroke()
    
        arrow_size = 10
    
        # Left arrow
        c.begin_path()
        c.move_to(start_x, timeline_y)
        c.line_to(start_x + arrow_size, timeline_y - arrow_size)
        c.line_to(start_x + arrow_size, timeline_y + arrow_size)
        c.close_path()
        c.fill_style = "black"
        c.fill()
    
        # Right arrow
        c.begin_path()
        c.move_to(end_x, timeline_y)
        c.line_to(end_x - arrow_size, timeline_y - arrow_size)
        c.line_to(end_x - arrow_size, timeline_y + arrow_size)
        c.close_path()
        c.fill()
    
        # Label
        center_x = (start_x + end_x) / 2
        c.fill_style = "black"
        c.font = "14px Arial"
        c.text_align = "center"
        c.text_baseline = "bottom"
        c.fill_text(el.name, center_x, timeline_y - 12)
    
        return

    elif el.kind == "flag":
        line_height = canvas_height / 6
        top_y = timeline_y - line_height
        c.stroke_style = "black"
        c.line_width = 2
        c.begin_path()
        c.move_to(x, timeline_y)
        c.line_to(x, top_y)
        c.stroke()
        if hasattr(el, 'flag_number') and el.flag_number is not None:
            c.fill_style = "maroon"
            c.font = "16px Arial"
            c.text_align = "center"
            c.text_baseline = "bottom"
            c.fill_text(str(el.flag_number), x, top_y - 4)
        return

    elif el.kind == "block":
        c.fill_style = pulse_fill_color(el)
        c.stroke_style = "black"
        c.line_width = 2
        c.fill_rect(x, top_y, width, height)
        c.stroke_rect(x, top_y, width, height)
        # Title centered
        c.fill_style = "black"
        c.font = "16px Arial"
        c.text_align = "center"
        c.text_baseline = "middle"
        c.fill_text(el.title, x + width/2, top_y + height/2)
        return
    
    elif el.kind == "grad":
        width = max(20, int(el.visual_width))
        height = el.visual_height
    
        center_x = x + width / 2
        baseline_y = timeline_y
    
        horizontal_radius = width / 2
        vertical_radius = height
    
        # --- Draw filled semi-ellipse using scaling ---
        c.save()
        c.translate(center_x, baseline_y)
        c.scale(1, vertical_radius / horizontal_radius)
    
        c.begin_path()
        c.move_to(-horizontal_radius, 0)
        c.arc(0, 0, horizontal_radius, math.pi, 0)
        c.close_path()
    
        c.fill_style = "lightgrey"
        c.fill()
        c.restore()
    
        # Outline
        vr = abs(vertical_radius)
        c.begin_path()
        c.ellipse(center_x, baseline_y,
                  horizontal_radius,
                  vr,
                  0,
                  math.pi if height > 0 else 0,
                  0 if height > 0 else math.pi)
        
        c.stroke_style = "black"
        c.line_width = 2
        c.stroke()

        # Baseline
        c.stroke_style = "black"
        c.line_width = 2
        c.begin_path()
        c.move_to(x, baseline_y)
        c.line_to(x + width, baseline_y)
        c.stroke()    
    
        # Title above
        c.fill_style = "black"
        c.font = "16px Arial"
        c.text_align = "center"
        c.text_baseline = "bottom"
        c.fill_text(el.title, center_x, baseline_y - height - 5)
        return

    elif el.kind == "shaped":
        width = max(20, int(el.visual_width))
        height = el.visual_height
    
        center_x = x + width / 2
        baseline_y = timeline_y
    
        horizontal_radius = width / 2
        vertical_radius = height
    
        # --- Draw filled semi-ellipse using scaling ---
        c.save()
        c.translate(center_x, baseline_y)
        c.scale(1, vertical_radius / horizontal_radius)
    
        c.begin_path()
        c.move_to(-horizontal_radius, 0)
        c.arc(0, 0, horizontal_radius, math.pi, 0)
        c.close_path()
    
        c.fill_style = "ghostwhite"
        c.fill()
        c.restore()
    
        # Outline
        vr = abs(vertical_radius)
        c.begin_path()
        c.ellipse(center_x, baseline_y,
                  horizontal_radius,
                  vr,
                  0,
                  math.pi if height > 0 else 0,
                  0 if height > 0 else math.pi)
        
        c.stroke_style = "black"
        c.line_width = 2
        c.stroke()

        # Baseline
        c.stroke_style = "black"
        c.line_width = 2
        c.begin_path()
        c.move_to(x, baseline_y)
        c.line_to(x + width, baseline_y)
        c.stroke()    

        # Title
        c.fill_style = "black"
        c.font = "16px Arial"
        c.text_align = "center"
        c.text_baseline = "bottom"
        c.fill_text(el.title, center_x, baseline_y - height - 5)

        return

    else:  # pulses
        if not hasattr(el, 'visual_height'):
            el.visual_height = DEFAULT_HEIGHT
            top_y = timeline_y - el.visual_height
        c.fill_style = pulse_fill_color(el)
        c.stroke_style = "black"
        c.line_width = 2
        c.fill_rect(x, top_y, width, el.visual_height)
        c.stroke_rect(x, top_y, width, el.visual_height)
        
        # Title
        c.fill_style = "black"
        c.font = "16px Arial"
        c.text_align = "center"
        c.text_baseline = "middle"
        c.fill_text(el.title, x + width/2, top_y - 10)
        
    
def draw_static_background():
    canvas.clear()
    canvas.fill_style = "white"
    canvas.fill_rect(0, 0, canvas.width, canvas.height)
    canvas.font = "16px Arial"

    # Vertical reference line
    canvas.stroke_style = "black"
    canvas.line_width = 1
    canvas.set_line_dash([6,6])
    canvas.stroke_line(40, 0, 40, canvas_height)
    canvas.set_line_dash([])

    # Solid timelines
    canvas.stroke_style = "black"
    canvas.line_width = 2
    for ch, y in timeline_positions.items():
        canvas.stroke_line(0, y, canvas.width, y)
        canvas.fill_text(ch.upper(), 10, y - 10)

    # FID example
    start_x = canvas.width - 70
    end_x = canvas.width
    amplitude = 55
    decay_constant = 0.05
    frequency = 0.35
    canvas.begin_path()
    timeline_y = timeline_positions["f1"]
    for x in range(start_x, end_x):
        t = x - start_x
        y = timeline_y - amplitude * math.exp(-decay_constant*t)*math.cos(frequency*t)
        if x == start_x:
            canvas.move_to(x, y)
        else:
            canvas.line_to(x, y)
    canvas.line_width = 2
    canvas.stroke()

    # Assign flag numbers
    flags = [el for el in sequence.elements if el.kind == "flag"]
    flags.sort(key=lambda e: e.start)
    for i, flag in enumerate(flags):
        flag.flag_number = i + 3 if i +3 < 63 else None

    # Draw all elements
    for el in sorted(sequence.elements, key=lambda e: e.start):
        draw_element(canvas, el)

def draw_dragging_element():
    dynamic_canvas.clear()
    if dragging_el:
        draw_element(dynamic_canvas, dragging_el)

def draw_sequence():
    draw_static_background()
    draw_dragging_element()
    canvas.flush()
    dynamic_canvas.flush()


# -----------------------
# Elements Panel
# -----------------------
def build_elements_panel():

    # --- Pulses row (var, 90, 180) ---
    pulse_buttons = [
        create_element_button("pulse", f)
        for f in element_files.get("pulse", [])
    ]

    pulse_row = HBox(
        pulse_buttons,
        layout=Layout(
            display="flex",
            justify_content="flex-start",
            align_items="center",
            overflow="hidden",
            gap="4px"
        )
    )
    
    # --- Shaped + Gradient row (sp1, grad) ---
    shaped_grad_buttons = []

    for f in element_files.get("shaped", []):
        shaped_grad_buttons.append(create_element_button("shaped", f))

    for f in element_files.get("grad", []):
        shaped_grad_buttons.append(create_element_button("grad", f))

    shaped_grad_row = HBox(
        shaped_grad_buttons,
        layout=Layout(
            justify_content="center",
            gap="6px",
            overflow="hidden"
        )
    )

    # --- Block + Flag row (CPD, flag) ---
    block_flag_buttons = []

    for f in element_files.get("block", []):
        block_flag_buttons.append(create_element_button("block", f))

    for f in element_files.get("flag", []):
        block_flag_buttons.append(create_element_button("flag", f))

    block_flag_row = HBox(
        block_flag_buttons,
        layout=Layout(
            justify_content="center",
            gap="6px",
            overflow="hidden"
        )
    )

    return VBox(
        [
            pulse_row,
            shaped_grad_row,
            block_flag_row
        ],
        layout=Layout(
            width="220px",
            align_items="center",
            gap="6px",
            margin="0 15px 0 0",
            overflow="hidden",
        )
    )

    return panel


elements_panel = build_elements_panel()

# -----------------------
# Canvas + Coherence
# -----------------------

coherence_label = Label(
    value=sequence.coherence_summary()
)

canvas_section = VBox([
    HTML("""
    <div style="
        text-align:center;
        font-size:15px;
        font-weight:bold;
    ">
        &nbsp;
    </div>
    """),
    canvas_box,
    coherence_label
],
layout=Layout(
    padding="0 25px 0 0"
))

elements_section = VBox([
    HTML("""
    <div style="
        text-align:center;
        font-size:15px;
        font-weight:bold;
    ">
        Elements
    </div>
    """),
    elements_panel
])

canvas_container.layout.min_width  = f"{canvas_width}px"
canvas_container.layout.min_height = f"{canvas_height}px"
canvas_container.layout.width  = f"{canvas_width}px"
canvas_container.layout.height = f"{canvas_height}px"
canvas_container.layout.overflow = "hidden"
canvas_container.layout.align_items = "center"
elements_section.layout = Layout(width="220px",overflow="hidden")
property_editor_box.layout.flex = "0 0 230px"


# -----------------------
# Mouse actions
# -----------------------
# Temporary state during drag
drag_temp_start = 0
drag_temp_width = 0
drag_temp_height = 0

def on_canvas_mouse_down(x, y):
    global dragging_el, drag_mode, drag_start_x, drag_start_y
    global drag_temp_start, drag_temp_width, drag_temp_height

    drag_start_y = y

    for el in reversed(sequence.elements):
    
        if el.kind == "delay" and not allow_delay_selection:
            continue
    
        if el.kind == "flag":
    
            timeline_y = timeline_positions.get(el.channel, 150)
    
            rect_x = el.start * timeline_scale - 20
            rect_w = 40
    
            rect_top = timeline_y - 140
            rect_h = 160
    
        elif el.kind == "delay":
    
            rect_x = el.start * timeline_scale
            rect_w = el.visual_width
    
            timeline_y = timeline_positions["f1"] - 30
            rect_h = 60
            rect_top = timeline_y - rect_h / 2
    
        else:
    
            rect_x = el.start * timeline_scale
            rect_w = el.visual_width
    
            timeline_y = timeline_positions.get(el.channel, 150)
            rect_h = el.visual_height
            rect_top = timeline_y - rect_h
    
        if (rect_x <= x <= rect_x + rect_w and
                rect_top <= y <= rect_top + rect_h):
    
            dragging_el = el
            drag_start_x = x
            drag_start_y = y
    
            drag_mode = "move"
    
            drag_temp_start = el.start
            drag_temp_width = el.visual_width
            drag_temp_height = el.visual_height
    
            draw_sequence()
            show_property_editor(el)
            return
                
    # If creating a new element inside a delay
    kind = selected_element.get("kind")
    file_path = selected_element.get("file_path")
    dash_x = 80

    if allow_delay_selection:
        print("Delay selection ON: cannot place new elements inside delays.")
        return
        
    if not kind or not file_path or x < dash_x:
        print("Cannot place element before the reference line.")
        return

    pulse_unit = 2
    start_time = x / timeline_scale
    new_start = round(start_time / pulse_unit) * pulse_unit
    duration = read_pulse_duration(file_path)
    channel = get_nearest_channel(y, kind)
    
    fid_start_time = get_fid_start_time()
    end_time = new_start + duration
    
    # Only restriction: everything except blocks on f2
    if not (kind == "block" and channel == "f2"):
        if new_start >= fid_start_time:
            print("Cannot place elements during FID.")
            return
        if end_time > fid_start_time:
            print("Element would overlap with FID.")
            return
    
    if has_channel_time_conflict(channel, new_start, duration):
        print("Conflict: element already exists at this time on this channel.")
        return

    # Create new element
    save_state()
    new_el = SequenceElement(kind, file_path, new_start, duration)
    new_el.channel = channel
    
    # Apply unified defaults for any kind (pulse/shaped/grad/...)
    apply_placement_defaults(new_el)
    
    sequence.add(new_el)
    rebuild_global_delays()
    renumber_delays()
    draw_sequence()
    coherence_label.value = sequence.coherence_summary()
    
def on_canvas_mouse_move(x, y):
    global drag_temp_start, drag_temp_width, drag_temp_height, drag_start_x, drag_start_y

    if not dragging_el:
        return

    delta_x = x - drag_start_x
    delta_y = drag_start_y - y

    dash_x = 80
    dash_time = dash_x / timeline_scale

    drag_temp_start += delta_x / timeline_scale

    # Prevent dragging before reference line
    if drag_temp_start < dash_time:
        drag_temp_start = dash_time
    
    drag_temp_channel = get_nearest_channel(y, dragging_el.kind)
    fid_start_time = get_fid_start_time()
    end_time = drag_temp_start + (drag_temp_width / timeline_scale)
    
    # Restrict everything except blocks on f2
    if not (dragging_el.kind == "block" and drag_temp_channel == "f2"):
        if drag_temp_start >= fid_start_time:
            return
        if end_time > fid_start_time:
            return
    
    drag_temp_width = max(MIN_WIDTH, drag_temp_width)
    drag_temp_height = max(MIN_HEIGHT, drag_temp_height)

    dynamic_canvas.clear()
    temp_el = copy.copy(dragging_el)
    temp_el.start = drag_temp_start
    temp_el.visual_width = drag_temp_width
    temp_el.visual_height = drag_temp_height
    temp_el.channel = drag_temp_channel
    draw_element(dynamic_canvas, temp_el)

    drag_start_x = x
    drag_start_y = y
    
def on_canvas_mouse_up(x, y):
    global dragging_el, drag_mode, drag_temp_start, drag_temp_width, drag_temp_height

    if not dragging_el:
        return

    save_state()

    pulse_unit = 2
    dragging_el.start = round(drag_temp_start / pulse_unit) * pulse_unit
    dragging_el.visual_width = drag_temp_width
    dragging_el.visual_height = drag_temp_height
    dragging_el.channel = get_nearest_channel(y, dragging_el.kind)

    dash_x = 80
    dash_time = dash_x / timeline_scale
    
    fid_start_time = get_fid_start_time()
    end_time = dragging_el.start + dragging_el.visual_width / timeline_scale
    
    # Restrict everything except blocks on f2
    if not (dragging_el.kind == "block" and dragging_el.channel == "f2"):
        if dragging_el.start >= fid_start_time:
            dragging_el.start = fid_start_time - dragging_el.visual_width / timeline_scale
        if end_time > fid_start_time:
            dragging_el.visual_width = (fid_start_time - dragging_el.start) * timeline_scale
    if dragging_el.start < dash_time:
        dragging_el.start = dash_time

    rebuild_global_delays()
    renumber_delays()

    dragging_el = None
    drag_mode = None

    dynamic_canvas.clear()
    draw_sequence()
    coherence_label.value = sequence.coherence_summary()
    
canvas.on_mouse_down(on_canvas_mouse_down)
canvas.on_mouse_move(on_canvas_mouse_move)
canvas.on_mouse_up(on_canvas_mouse_up)

# -----------------------
# Canvas size controls
# -----------------------
canvas_width_input = IntText(
    description="Canvas width:",
    value=canvas_width,
    layout=Layout(width="160px"),
    style={'description_width': '75px'}
)

apply_canvas_size_btn = Button(
    description="Update",
    button_style="info",
    layout=Layout(width="250px")
)

def on_apply_canvas_size(_):
    set_canvas_size(canvas_width_input.value, canvas_height)

apply_canvas_size_btn.on_click(on_apply_canvas_size)

canvas_size_row = HBox(
    [canvas_width_input, apply_canvas_size_btn]
)

# -----------------------
# Buttons row
# -----------------------

buttons_row = HBox(
    [
        delete_button,
        undo_button,
        clear_button,
        toggle_delays_btn,
        browser_download_button,
        phase_cycle_checkbox,
        browser_download_link,
        export_btn,
        canvas_size_row,
    ],
    layout=Layout(
        spacing='10px',
        padding='5px 0px'
    )
)

# -----------------------
# Definitions tabs
# -----------------------

def load_defs(filename: str):
    """Load a definition file from packaged resources for display."""
    try:
        content = read_resource_text("defs", filename)
    except FileNotFoundError:
        return HTML(
            f"<pre>No definition file found: defs/{filename}</pre>"
        )

    return HTML(f"<pre>{content}</pre>")

defs_files = {
    "pulse": "pulse_def.txt",
    "power": "power_def.txt",
    "delay": "delay_def.txt",
    "cnst": "cnst_def.txt",
    "loops": "loops_def.txt"
}

pulse_tab = load_defs("pulse")
power_tab = load_defs("power")
shaped_tab = load_defs("shaped")
delay_tab = load_defs("delay")
cnst_tab = load_defs("cnst")
loops_tab = load_defs("loops")

defs_tabs = Tab()

tab_widgets = []
tab_titles = []

for name, filename in defs_files.items():

    tab_widgets.append(load_defs(filename))
    tab_titles.append(name)

defs_tabs.children = tab_widgets

for i, title in enumerate(tab_titles):
    defs_tabs.set_title(i, title)

defs_tabs.layout = Layout(
    width="500px",
    height="220px",
    overflow="auto"
)

defs_section = VBox([
    HTML("<b style='font-size:15px'>Definitions</b>"),
    defs_tabs
])

# -----------------------
# Layout
# -----------------------

top_bar = HBox(
    [
        buttons_row
    ],
    layout=Layout(
        justify_content="space-between",
        width='100%',
        padding='5px 0px'
    )
)

main_top_row = HBox(
    [
        elements_section,
        canvas_section,
        phase_cycle_box,
        property_editor_box
    ],
    layout=Layout(
        justify_content="flex-start",
        gap="10px"
    )
)

exp_prop_row_1 = HBox(
    [exp_title, exp_class, exp_dim, exp_2d_option, pulse_section, shape_section],
    layout=Layout(spacing="1px"),
    padding='20px 20px'    
)

exp_prop_row_2 = HBox(
    [exp_type, exp_subtype, exp_incl, ns_text, ds_text, exp_comment],
    layout=Layout(spacing="1px"),
    padding='20px 20px' 
)

exp_prop_section = VBox([
    exp_prop_row_1,
    exp_prop_row_2
])

app_title = HTML(f"""
<div style="
    text-align:center;
    font-size:48px;
    font-weight:bold;
    color:#0071BC;
    margin-top:10px;
    margin-bottom:15px;">

<span style="
    display:inline-block;
    border-bottom:5px solid #BC4B00;
    padding-bottom:8px;">
    NMR
</span>p<span style="
    display:inline-block;
    border-bottom:5px solid #BC4B00;
    padding-bottom:8px;
    padding-right:0.5em;">
    aint
</span><span style="
    position:relative;
    left:-0.70em;">
    🖌️
</span>

</div>
""")

copyright_footer = HTML(f"""
<hr>
<div style="
    text-align:center;
    font-size:14px;
    color:#666;">
    NMRpaint v{VERSION} | Pulse Program Generator<br>
    © 2026 Alex van der Ham
</div>
""")

app_wrapper = HTML("""
<div style="
    position:fixed;
    top:0;
    left:0;
    width:100vw;
    height:100vh;
    background:#F5F5F5;
    z-index:-999;
">
</div>
""")

main_vbox = VBox(
    [
        app_wrapper,
        app_title,
        top_bar,
        exp_prop_section,
        generation_output,
        main_top_row,
        copyright_footer,
    ],
)


#initial d1 arrow with update logic
dash_x = 40
fid_start_time = (canvas.width - 83) / timeline_scale

delay_file = DELAY_RESOURCE_ID
delay = SequenceElement(
    kind="delay",
    file_path=delay_file,
    start=dash_x / timeline_scale,
    duration=fid_start_time - dash_x / timeline_scale,
    channel="f1",
    name="d1"
)

sequence.add(delay)
draw_sequence()

def create_app():
    """Return the complete NMRpaint widget application."""
    return main_vbox


if __name__ == "__main__":
    display(create_app())
