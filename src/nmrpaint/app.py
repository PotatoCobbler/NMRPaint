from .exporters import (
    build_png_download_link_html,
    build_text_download_href,
    normalize_output_filename,
    save_text_local,
    write_text_file,
)

from .resource_manager import (
    list_resource_names,
    read_resource_text,
    resource_exists,
)

import copy, re, tempfile, time, math, json
from datetime import datetime
from io import StringIO
from pathlib import Path, PurePosixPath

from ipycanvas import Canvas
from ipywidgets import (
    Box, Button, Checkbox, Dropdown, FloatText, HBox, HTML,
    ToggleButton,
    IntText, Label, Layout, Output, SelectMultiple, Tab, Text, Textarea, VBox,
)
from IPython.display import HTML as DisplayHTML, display

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
timeline_positions = {"f1": 110, "f2": 210, "Gz": 310}

# -----------------------
# Coherence-order positions
# -----------------------

ctp_channel_positions = {
    "f1": {
         3:  60,
         2:  80,
         1: 100,
         0: 120,
        -1: 140,
        -2: 160,
        -3: 180,
    },

    "f2": {
         3: 230,
         2: 250,
         1: 270,
         0: 290,
        -1: 310,
        -2: 330,
        -3: 350,
    }
}

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
        self.description = ""                     
        self.power = power
        self.phase = phase
        self.shape = shape
        self.visual_width = self.duration * timeline_scale
                     
        #wavemaker specific attributes
        self.wvm = False
        self.powerindex = ""
        self.subname = ""
        self.length = ""
        self.stepsize = ""
        self.bandwidth = ""
        self.Q = ""
        self.sweepdirection = ""
                     
        #Specials; flags, delays, blocks
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
        return f"          Total elements: {len(self.elements)}"

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

def get_phase_delta(el):

    for row in phase_rows:
        if row["element"] is el:
            try:
                return int(row["delta"].value)
            except (ValueError, TypeError):
                return 0

    return 0
    
def build_phase_delta_map():
    return {
        id(row["element"]): int(row["delta"].value)
        for row in phase_rows
        if row.get("element") is not None
    }
    
def draw_ctp_horizontal(c, x0, x1, y):

    c.begin_path()
    c.move_to(x0, y)
    c.line_to(x1, y)
    c.stroke()

def draw_ctp_diagonal(c, x0, x1, y0, y1):

    c.begin_path()
    c.move_to(x0, y0)
    c.line_to(x1, y1)
    c.stroke()

def clear_phase_cycle_gui():
    phase_rows.clear()
    phase_cycle_container.children = ()
    phase_cycle_output.value = ""
    
#--------------
#wvm attributes
#--------------
field_layout = Layout(width="200px")
label_style = {"description_width": "85px"}

el_powerindex = Text(
    description="Power Index",
    value="",
    layout=field_layout,
    style=label_style
)

el_subname = Text(
    description="Subname",
    value="",
    layout=field_layout,
    style=label_style
)

el_length = Text(
    description="Length (ms)",
    value="",
    layout=field_layout,
    style=label_style
)

el_stepsize = Text(
    description="Step Size (us)",
    value="",
    layout=field_layout,
    style=label_style
)

el_bandwidth = Text(
    description="Δω (kHz)",
    value="",
    layout=field_layout,
    style=label_style
)

el_Q = Text(
    description="Q",
    value="",
    layout=field_layout,
    style=label_style
)

el_wvm = Checkbox(
    description="wvm",
    value=False,
    layout=field_layout,
    style=label_style
)

el_sweepdirection = Dropdown(
    description="Sweep",
    options=["", "lowToHigh", "highToLow"],
    layout=field_layout,
    style=label_style
)

el_powerindex.value = ""
el_subname.value = ""
el_length.value = ""
el_stepsize.value = ""
el_bandwidth.value = ""
el_Q.value = ""
el_sweepdirection.value = ""

wvm_box = VBox(
    [
        el_powerindex,
        el_subname,
        el_length,
        el_stepsize,
        el_bandwidth,
        el_Q,
        el_sweepdirection,
    ],
    layout=Layout(width="210px")
)

wvm_box.layout.display = "none"

def update_wvm_visibility(change=None):
    wvm_box.layout.display = "flex" if el_wvm.value else "none"

el_wvm.observe(update_wvm_visibility, names="value")

# ----------------
# Allowed channels
# ----------------

allowed_channels = {
    "pulse": ["f1", "f2"],
    "shaped": ["f1", "f2"],
    "block": ["f1", "f2"],
    "flag": ["f1", "f2"],
    "grad": ["Gz"]
}

#----------------------
#Nearest channel logic
#----------------------

drag_start_y = 0

def get_nearest_channel(y, kind=None):
    candidates = timeline_positions
    if kind in allowed_channels:
        # Only channels allowed for this kind
        candidates = {ch: timeline_positions[ch] for ch in allowed_channels[kind]}
    
    distances = {ch: abs(y - pos) for ch, pos in candidates.items()}
    return min(distances, key=distances.get)


#---------------------
# Delay related logic
#---------------------

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
            
def rebuild_global_delays(preferred_delays=None):
    global sequence_dirty
    preferred_delays = list(preferred_delays or [])
    existing_delays = [el for el in sequence.elements if el.kind == "delay"]
    old_delays = []
    for el in preferred_delays + sorted(existing_delays, key=lambda e: (not getattr(e, "manual", False), e.start)):
        if el not in old_delays:
            old_delays.append(el)
    
    sequence.elements = [
        el for el in sequence.elements
        if el.kind != "delay" or getattr(el, "manual", False)
    ]

    dash_x = 40 / timeline_scale
    fid_start_time = (canvas.width - 83) / timeline_scale
    delay_file = DELAY_RESOURCE_ID

    def create_delay(start, duration):
    
        # Do not create delays shorter than 5
        if duration < 5:
            return
    
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
    
    # Delays during acquisition/FID are not drawable sequence elements.
    fid_limit = fid_start_time
    for _el in list(sequence.elements):
        if _el.kind != "delay":
            continue
        if _el.start >= fid_limit:
            sequence.elements.remove(_el)
            continue
        _el.duration = min(_el.duration, max(0.0, fid_limit - _el.start))
        _el.visual_width = _el.duration * timeline_scale

    sequence_dirty = True
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
    draw_ctp()
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
    global sequence_dirty
    global sequence
    if not history:
        return

    sequence = history.pop()
    sequence_dirty = True
    refresh_ui()

def clear_sequence(b):
    global sequence_dirty

    save_state()
    sequence.elements.clear()
    clear_phase_cycle_gui()
    
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
    sequence_dirty = True
    refresh_ui()

def delete_selected_element(b):
    global sequence_dirty, current_element
    if current_element is None:
        print("No element selected."); return
    if current_element not in sequence.elements:
        current_element = None; return
    if current_element.kind == "delay":
        delay = current_element
        name = str(getattr(delay, "name", "") or "").strip().lower()
        if name == "d1":
            print("d1 cannot be deleted."); current_element = None; return
        delays = [e for e in sequence.elements if e.kind == "delay" and e is not delay]
        tol = 1e-6
        left = max((e for e in delays if abs(e.start + e.duration - delay.start) <= tol), key=lambda e:e.start, default=None)
        right = min((e for e in delays if abs(e.start - delay.start - delay.duration) <= tol), key=lambda e:e.start, default=None)
        if left is None and right is None:
            print("This delay cannot be deleted: an existing delay must be immediately to its left or right."); current_element=None; return
        save_state()
        if left is not None:
            left.duration += delay.duration; left.visual_width = left.duration * timeline_scale; survivor=left
        else:
            right.start = delay.start; right.duration += delay.duration; right.visual_width = right.duration * timeline_scale; survivor=right
        sequence.elements.remove(delay); sequence_dirty=True
        rebuild_global_delays(preferred_delays=[survivor]); refresh_ui()
        print(f"Deleted delay: {delay.name}"); current_element=None; return
    save_state(); sequence.elements.remove(current_element); sequence_dirty=True
    rebuild_global_delays(); refresh_ui(); print(f"Deleted element: {current_element.name}"); current_element=None

# -----------------------
# Button Creation
# -----------------------
clear_button = Button(
    button_style="danger",
    description="Clear",
    tooltip="Reset everything"
)

undo_button = Button(
    description="Undo",
    tooltip="Undo last action"
)

delete_button = Button(
    description="Delete",
    tooltip="Delete selected element"
)

toggle_delays_btn = Button(
    description="Delay Selection",
    button_style="info",
    tooltip="Click to allow selecting delay elements"
)


phase_cycle_checkbox = Checkbox(
    value=False,
    description="Include phase table",
    indent=False,
    layout=Layout(
        width="auto",
    ),
)

print_names_button = Button(
    description="Generate",
    button_style="primary"
)

export_btn = Button(
    description="Export Canvas",
    button_style="warning",
    tooltip="Download pulse sequence image"
)

canvas_download_link = HTML()

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

browser_download_link = HTML()

#-----------------------------------
# Export png function (not working)
#-----------------------------------
def export_png(b):

    try:
        canvas.sync_image_data = True
        draw_sequence()

        canvas.flush()
        time.sleep(0.5)
        
        filename = normalize_output_filename(
            exp_title.value,
            default="sequence",
        )

        if not filename.lower().endswith(".png"):
            filename += ".png"

        with tempfile.NamedTemporaryFile(
            suffix=".png",
            delete=False,
        ) as tmp:
            tmp_path = tmp.name

        canvas.to_file(tmp_path)

        with open(tmp_path, "rb") as file:
            png_bytes = file.read()

        canvas_download_link.value = build_png_download_link_html(
            png_bytes=png_bytes,
            filename=filename,
            label="Download Canvas PNG",
        )

    except Exception as exc:
        canvas_download_link.value = (
            f"<pre>Export failed: {exc}</pre>"
        )

    finally:
        canvas.sync_image_data = False

export_btn.on_click(export_png)

# ------------------------
# User-defined definitions
# ------------------------

definitions_text = Textarea(
    value="",
    layout=Layout(
        width="98%",
        height="245px"
    )
)

# -----------------------
# Canvas <-> text conversion
# -----------------------

def _nmrpaint_element_metadata(el, body_lines=1):
    data = {"kind":el.kind,"file_path":el.file_path,"start":float(el.start),"duration":float(el.duration),"channel":el.channel,"title":el.title,"name":el.name,"definition":el.definition,"power":el.power,"phase":el.phase,"shape":el.shape,"body_lines":int(body_lines),"manual":bool(getattr(el,"manual",False)),"wvm":bool(getattr(el,"wvm",False)),"powerindex":getattr(el,"powerindex",""),"subname":getattr(el,"subname",""),"length":getattr(el,"length",""),"stepsize":getattr(el,"stepsize",""),"bandwidth":getattr(el,"bandwidth",""),"Q":getattr(el,"Q",""),"sweepdirection":getattr(el,"sweepdirection","")}
    return ";@NMRPAINT " + json.dumps(data,separators=(",",":"),ensure_ascii=False)


def _delay_duration_from_definition(name, default=10.0):
    """Return a graphical duration for a Bruker delay definition.

    Definitions are normally stored in defs/delay_def.txt.  Values such as
    4u, 2.5m, or 1s are converted to the canvas time unit (microseconds).
    """
    key = str(name or "").strip().lower()
    try:
        text = read_resource_text("defs", "delay_def.txt")
    except Exception:
        return float(default)

    for raw in text.splitlines():
        if ":" not in raw:
            continue
        lhs, rhs = raw.split(":", 1)
        if lhs.strip().lower() != key:
            continue
        m = re.search(r"([-+]?\d+(?:\.\d+)?)\s*(u|us|m|ms|s)?", rhs.strip(), re.I)
        if not m:
            return float(default)
        value = float(m.group(1))
        unit = (m.group(2) or "u").lower()
        if unit in ("m", "ms"):
            value *= 1000.0
        elif unit == "s":
            value *= 1_000_000.0
        return value
    return float(default)


def _internal_delay_metadata(el, rendered, fid_start):
    """Create metadata for explicit dXX statements embedded in an element definition."""
    out = []
    cursor = float(el.start) + float(el.duration)
    for raw in str(rendered).splitlines():
        st = raw.strip()
        m = re.fullmatch(r"d(\d+)", st, re.I)
        if not m:
            continue
        name = "d" + m.group(1)
        duration = _delay_duration_from_definition(name)
        if cursor >= fid_start:
            continue
        duration = min(duration, max(0.0, fid_start - cursor))
        if duration <= 0:
            continue
        d = {
            "kind": "delay",
            "file_path": DELAY_RESOURCE_ID,
            "start": cursor,
            "duration": duration,
            "channel": "f1",
            "title": "",
            "name": name,
            "definition": "",
            "power": None,
            "phase": None,
            "shape": None,
            "body_lines": 1,
            "manual": True,
            "wvm": False,
            "powerindex": "",
            "subname": "",
            "length": "",
            "stepsize": "",
            "bandwidth": "",
            "Q": "",
            "sweepdirection": "",
            "internal": True,
        }
        out.append(d)
        cursor += duration
    return out

def _nmrpaint_element_from_metadata(data):
    el=SequenceElement(kind=data.get("kind","pulse"),file_path=data.get("file_path",""),start=float(data.get("start",0)),duration=float(data.get("duration",10)),channel=data.get("channel","f1"),title=data.get("title",""),name=data.get("name",""),definition=data.get("definition",""),power=data.get("power"),phase=data.get("phase"),shape=data.get("shape"))
    el.manual=bool(data.get("manual",False)); el.wvm=bool(data.get("wvm",False))
    for a in ("powerindex","subname","length","stepsize","bandwidth","Q","sweepdirection"): setattr(el,a,data.get(a,""))
    if el.kind=="delay": el.visual_width=el.duration*timeline_scale
    return el

def _fallback_resource(kind, token):
    token=(token or "").lower()
    if kind=="shaped": return next((x for x in element_files.get("shaped",[]) if resource_filename(x).lower()=="sp1.txt"),"elements/shaped/sp1.txt")
    if kind=="grad": return next(iter(element_files.get("grad",[])),"elements/grad/gp1.txt")
    if kind=="pulse":
        target={"p0":"p0.txt","p1":"p90.txt","p2":"p180.txt","p3":"p90.txt","p4":"p180.txt"}.get(token,"p90.txt")
        return next((x for x in element_files.get("pulse",[]) if resource_filename(x).lower()==target),f"elements/pulse/{target}")
    return DELAY_RESOURCE_ID

def _fallback_element(kind,token,start,channel="f1",phase=None,shape=None):
    fp=_fallback_resource(kind,token); el=SequenceElement(kind,fp,start,read_pulse_duration(fp),channel=channel,phase=phase,shape=shape); apply_placement_defaults(el)
    if phase: el.phase=phase
    if shape: el.shape=shape
    if kind in ("pulse","shaped","grad"): el.name=token.split(":",1)[0]
    return el

def parse_pulse_program_text(text,excluded_lines=()):
    excluded=set(excluded_lines or ()); lines=text.splitlines(); seq=PulseSequence(); cursor=40/timeline_scale; pending=[]; skip=0
    def add_meta(items):
        nonlocal cursor
        for d in items:
            e=_nmrpaint_element_from_metadata(d)
            # Embedded definition delays are sequential by construction.  If a
            # following explicit element was recorded at the pre-definition
            # start, move it past the embedded delay instead of duplicating the
            # same delay region during rebuild_global_delays().
            if d.get("internal") or (e.kind == "delay" and e.start < cursor):
                e.start = cursor
            seq.add(e)
            cursor=max(cursor,e.start+e.duration)
    for no,raw in enumerate(lines,1):
        if no in excluded: pending=[]; skip=0; continue
        st=raw.strip()
        if st.startswith(";@NMRPAINT "):
            try: pending.append(json.loads(st[len(";@NMRPAINT "):]))
            except json.JSONDecodeError: pass
            continue
        if pending:
            add_meta(pending); body=max(int(d.get("body_lines",1)) for d in pending); pending=[]; skip=max(0,body-1); continue
        if skip: skip-=1; continue
        if not st or st.startswith((";","#",'"')) or st.startswith("define "): continue
        if re.match(r"^(?:go|mc|exit)\b",st,re.I) or re.match(r"^(?:1|2)\s+ze\b",st,re.I): continue
        m=re.search(r"\(center\s+(.+?)\s*\)$",st,re.I)
        if m:
            for name,shape,phase,ch in re.findall(r"\((p\d+)(?::([A-Za-z0-9_]+))?\s+(ph\d+)\):([A-Za-z0-9]+)",m.group(1)):
                seq.add(_fallback_element("shaped" if shape else "pulse",f"{name}:{shape}" if shape else name,cursor,ch,phase,shape))
            continue
        m=re.search(r"\((p\d+):([A-Za-z0-9_]+)\s+(ph\d+)\):([A-Za-z0-9]+)",st)
        if m:
            n,sh,ph,ch=m.groups(); e=_fallback_element("shaped",f"{n}:{sh}",cursor,ch,ph,sh); seq.add(e); cursor+=e.duration; continue
        m=re.search(r"\((p\d+)\s+(ph\d+)\):([A-Za-z0-9]+)",st)
        if m:
            n,ph,ch=m.groups(); e=_fallback_element("pulse",n,cursor,ch,ph); seq.add(e); cursor+=e.duration; continue
        m=re.search(r"\b(p\d+):(gp\d+(?:\*[^\s]+)?)\b",st,re.I)
        if m:
            n,sh=m.groups(); e=_fallback_element("grad",n+":"+sh.split("*")[0],cursor,"Gz",shape=sh.split("*")[0]); seq.add(e); cursor+=e.duration; continue
        m=re.fullmatch(r"d([A-Za-z0-9_]+)",st,re.I)
        if m:
            e=SequenceElement("delay",DELAY_RESOURCE_ID,cursor,read_pulse_duration(DELAY_RESOURCE_ID),"f1",name="d"+m.group(1)); e.manual=True; seq.add(e); cursor+=e.duration
    if pending: add_meta(pending)

    # Acquisition/FID is not part of the drawable pulse-program timeline.
    # Remove delays that start in the FID and clamp any delay that crosses into it.
    fid_limit = get_fid_start_time()
    cleaned = []
    for e in seq.elements:
        if e.kind == "delay":
            if e.start >= fid_limit:
                continue
            e.duration = min(e.duration, max(0.0, fid_limit - e.start))
            if e.duration <= 0:
                continue
            e.visual_width = e.duration * timeline_scale
        cleaned.append(e)
    seq.elements = cleaned
    return seq

def _line_is_graphical(line):
    st=line.strip()
    if not st or st.startswith((";","#",'"')) or st.startswith("define "): return False
    if re.match(r"^(?:go|mc|exit)\b",st,re.I) or re.match(r"^(?:1|2)\s+ze\b",st,re.I): return False
    return bool(re.search(r"\(p\d+(?::[A-Za-z0-9_]+)?\s+ph\d+\):",st) or re.search(r"\(center\b",st,re.I) or re.search(r"\bp\d+:gp\d+",st,re.I) or re.fullmatch(r"d[A-Za-z0-9_]+",st) or re.match(r"^\d+(?:\s|$)",st))

def update_excluded_line_options(change=None):
    if "pulse_program_output" not in globals() or "excluded_lines_selector" not in globals(): return
    old=set(excluded_lines_selector.value); opts=[]
    for i,line in enumerate(pulse_program_output.value.splitlines(),1):
        sn=line.strip(); sn=sn if len(sn)<=58 else sn[:55]+"..."; v=f"{i}:{sn}"
        if not _line_is_graphical(line) and not line.strip().startswith(";@NMRPAINT "): old.add(v)
        opts.append((v,v))
    excluded_lines_selector.options=opts; excluded_lines_selector.value=tuple(v for v,_ in opts if v in old)

def canvas_to_text(b=None):
    try:
        populate_phase_rows()
        if phase_cycle_checkbox.value: generate_phase_cycle()
        pulse_program_output.value=build_pulse_program_text(include_nmrpaint_metadata=False); pulse_program_metadata_output.value=build_pulse_program_text(include_nmrpaint_metadata=True); update_excluded_line_options(); generation_output.layout.display="none"
    except Exception as exc:
        generation_output.layout.display="block"; generation_output.clear_output(wait=True)
        with generation_output: print(f"Canvas → Text failed: {type(exc).__name__}: {exc}")

def _merge_visible_text_with_metadata(visible_text, metadata_text):
    """Inject hidden NMRpaint metadata back into the visible pulse program.

    The user-facing text remains clean. Metadata is matched to graphical
    statements in their original order; if the visible text was edited,
    unmatched statements simply fall back to normal Bruker parsing.
    """
    if not metadata_text.strip():
        return visible_text

    groups = []
    pending = []
    for raw in metadata_text.splitlines():
        st = raw.strip()
        if st.startswith(";@NMRPAINT "):
            try:
                pending.append(json.loads(st[len(";@NMRPAINT "):]))
            except json.JSONDecodeError:
                pending = []
            continue
        if pending:
            groups.append((list(pending), max(int(d.get("body_lines", 1)) for d in pending)))
            pending = []
    if pending:
        groups.append((list(pending), max(int(d.get("body_lines", 1)) for d in pending)))

    if not groups:
        return visible_text

    out = []
    group_index = 0
    consume = 0
    for raw in visible_text.splitlines():
        if consume:
            out.append(raw)
            consume -= 1
            continue

        if _line_is_graphical(raw) and group_index < len(groups):
            meta_group, body_lines = groups[group_index]
            for d in meta_group:
                out.append(";@NMRPAINT " + json.dumps(d, separators=(",", ":"), ensure_ascii=False))
            out.append(raw)
            consume = max(0, body_lines - 1)
            group_index += 1
        else:
            out.append(raw)

    return "\n".join(out)


def text_to_canvas(b=None):
    global sequence,sequence_dirty,current_element
    try:
        excluded={int(v.split(":",1)[0]) for v in excluded_lines_selector.value}; source_text=_merge_visible_text_with_metadata(pulse_program_output.value, pulse_program_metadata_output.value); parsed=parse_pulse_program_text(source_text,excluded)
        if not parsed.elements: raise ValueError("No graphical elements could be reconstructed from the text.")
        save_state()
        sequence=parsed
        sequence_dirty=True
        current_element=None

        # Rebuild the automatic/global delays from the reconstructed canvas.
        # The sequence is now the source of truth, so regenerate BOTH text
        # representations afterwards.  This is important because Text →
        # Canvas may change element positions, durations, delay numbering,
        # or remove delays that fall inside the FID.  Leaving the previous
        # metadata untouched would make it describe the old canvas.
        rebuild_global_delays()
        clear_phase_cycle_gui()
        populate_phase_rows()
        if phase_cycle_checkbox.value:
            generate_phase_cycle()

        # Canonicalise the visible text as well as the hidden metadata from
        # the newly reconstructed canvas.  This guarantees that the two
        # representations remain one-to-one after every Text → Canvas
        # operation, including cases where automatic delays were rebuilt.
        pulse_program_output.value=build_pulse_program_text(include_nmrpaint_metadata=False)
        pulse_program_metadata_output.value=build_pulse_program_text(include_nmrpaint_metadata=True)

        refresh_ui()
        update_excluded_line_options()
        generation_output.layout.display="none"
    except Exception as exc:
        generation_output.layout.display="block"; generation_output.clear_output(wait=True)
        with generation_output: print(f"Text → Canvas failed: {type(exc).__name__}: {exc}")

# -----------------------
# Main Pulse Program Generator
# -----------------------

cpd_pulses = set()
cpd_delays = set()
cpd_powers = set()
cpd_phases = set()
cpd_shapes = set()
cpd_gradients = set()

def build_pulse_program_text(include_phase_cycle: bool = False, include_nmrpaint_metadata: bool = False) -> str:
    """Build and return the Bruker pulse-program text."""
    # Clear previous
    cpd_pulses.clear()
    cpd_delays.clear()
    cpd_powers.clear()
    cpd_phases.clear()
    cpd_shapes.clear()
    cpd_gradients.clear()
    
    f = StringIO()

    # -----------------------
    # Header section
    # -----------------------
    f.write(f";{exp_title.value}\n")
    f.write(f";avance-version ({datetime.now().strftime('%Y-%m-%d')})\n")
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
    
    has_gradients = any(
        el.kind.lower() == "grad"
        for el in sequence.elements
    )
    
    has_dante = False
    
    for el in sequence.elements:
    
        if el.kind.lower() != "block":
            continue
    
        title = el.title.strip().lower()
        channel = el.channel.strip().lower()
    
        # DANTE requires Daz.incl
        if title == "dante":
            has_dante = True
    
        # Check block contents for gradients
        cpd_filename = f"{title}_{channel}.txt"
    
        if resource_exists("cpdlib", cpd_filename):
    
            block_text = read_resource_text(
                "cpdlib",
                cpd_filename
            )
    
            if re.search(r"\bgp\d+\b", block_text):
                has_gradients = True
    
    if has_gradients:
        f.write("#include <Grad.incl>\n")
    
    if has_dante:
        f.write("#include <Daz.incl>\n")
    
    delay_keywords = ["delta", "tau", "Delta", "Tau", "epsilon", "δ", "Δ", "τ", "ε", "☺"]

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
    # User definitions
    # -----------------------
    if definitions_text.value.strip():
        f.write(definitions_text.value.rstrip() + "\n\n")
            
    # ----------------------------------------
    # ACQT0 correction based on final element
    # ----------------------------------------
    if not sequence.elements:
    
        f.write('"acqt0=0"\n\n')
    
    else:
    
        # Find the element furthest to the right on the canvas
        last_el = max(
            sequence.elements,
            key=lambda el: el.start + el.duration
        )
    
        kind = str(last_el.kind).strip().lower()
    
        if kind in ("pulse", "shaped"):
    
            pulse = last_el.name
    
            # Final pulse is p1 or p3
            if pulse in ("p1", "p3"):
    
                f.write(f'"acqt0=-{pulse}*2/PI"\n\n')
    
            else:
    
                # Reference pulse depends on channel
                if last_el.channel == "f1":
                    basepulse = "p1"
    
                elif last_el.channel == "f2":
                    basepulse = "p3"
    
                else:
                    basepulse = None
    
                if basepulse is not None:
    
                    f.write(
                        f'"acqt0=-tan(({pulse}/{basepulse})*(PI/4))*'
                        f'{basepulse}*2/PI"\n\n'
                    )
    
                else:
    
                    f.write('"acqt0=0"\n\n')
    
        else:
    
            # Final element is a delay, gradient, etc.
            f.write('"acqt0=0"\n\n')    
            
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
        row["gp"].value
        for row in shape_dropdowns
        if row["gp"].value
    }

    ea_map = {}

    if exp_2d_option.value == "Echo-Antiecho":
        selected = []
        
        for row in shape_dropdowns:
        
            gp = row["gp"].value
        
            if not gp:
                continue
        
            sign = row["sign"].value
        
            selected.append((gp, sign))
        
        ea_map = {}
        
        multiple = len(selected) > 1
        
        for i, (gp, sign) in enumerate(selected, start=1):
        
            suffix = f"*EA{i}" if multiple else "*EA"
        
            if sign == "+":
                ea_map[gp] = suffix
            else:
                ea_map[gp] = f"*-1{suffix}"

    def write_grad(el):
    
        gradients = sorted(
            [g for g in sequence.elements if g.kind.lower() == "grad"],
            key=lambda g: g.start
        )
    
        gp = f"gp{gradients.index(el)+1}"
            
        if gp in ea_map:
            gp += ea_map[gp]
    
        return f" {el.name}:{gp}\n d16"
        
    def write_block(el):
    
        title = el.title.strip().lower()
        channel = el.channel.strip().lower()
    
        cpd_filename = f"{title}_{channel}.txt"
    
        # Get block text
        if resource_exists("cpdlib", cpd_filename):
    
            text = read_resource_text(
                "cpdlib",
                cpd_filename
            )
    
        elif channel == "f2":
    
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

        # ---------------------------------------
        # Normalize whitespace
        # ---------------------------------------
    
        # Convert non-breaking spaces to ordinary spaces
        text = text.replace("\u00a0", " ")
    
        # Remove trailing whitespace from every line
        lines = [
            line.rstrip()
            for line in text.splitlines()
        ]
    
        # Remove completely empty lines at beginning/end
        while lines and not lines[0].strip():
            lines.pop(0)
    
        while lines and not lines[-1].strip():
            lines.pop()
    
        text = "\n".join(lines)
        
        # Extract CPD parameters
        cpd_pulses.update(
            re.findall(r"\bp\d+\b", text)
        )
    
        cpd_delays.update(
            re.findall(r"\bd\d+\b", text)
        )
    
        cpd_powers.update(
            re.findall(r"\bpl\d+\b", text)
        )
    
        cpd_phases.update(
            re.findall(r"\bph\d+\b", text)
        )
    
        shape_matches = re.findall(
            r"\bp\d+:([A-Za-z0-9_]+)",
            text
        )

        cpd_gradients.update(
            re.findall(r"\bgp\d+\b", text)
        )
    
        for shape in shape_matches:
    
            # Exclude gradient/channel identifiers
            if shape.lower() in {
                "f1", "f2", "f3", "f4",
                "gp1", "gp2", "gp3", "gp4", "gp5", "gp6", "gp7", "gp8",
                "gpx", "gpy", "gpz",
            }:
                continue
    
            cpd_shapes.add(shape)
    
        return text.strip()
        
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
    
        #if kind == "delay":
        #    return f"({el.name})"
            
        if kind == "grad":
            return f"({el.name}:{el.shape})"    
            
        return None
        
    # -----------------------
    # Element dictionary
    # -----------------------        
    ELEMENT_WRITERS = {
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
    for el in sequence.elements:
    
        if not (el.kind.lower() == "shaped" and getattr(el, "wvm", False)):
            continue
    
        args = [el.shape, el.title]
    
        def format_value(v):
            if not v:
                return None
            v = str(v).strip()
            if v.startswith("cnst"):
                v = "$" + v
            return v
    
        # powerIndex
        v = format_value(el.powerindex)
        if v:
            args.append(f"powerIndex={v}")
    
        # name (subname)
        v = format_value(el.subname)
        if v:
            args.append(f"name={v}")
    
        # length (ms)
        v = format_value(el.length)
        if v:
            args.append(f"length={v} ms")
    
        # stepSize (us)
        v = format_value(el.stepsize)
        if v:
            args.append(f"stepSize={v} us")
    
        # bandwidth (Hz)
        v = format_value(el.bandwidth)
        if v:
            args.append(f"bandwidth={v} Hz")
    
        # Q
        v = format_value(el.Q)
        if v:
            args.append(f"Q={v}")
    
        # sweepDirection
        v = format_value(el.sweepdirection)
        if v:
            args.append(f"sweepDirection={v}")
    
        f.write(f"create_shape({', '.join(args)})\n\n")
        
#------
#
#------
    
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
        
            writer = ELEMENT_WRITERS.get(kind)
        
            if writer:
                rendered=writer(el)
                if include_nmrpaint_metadata:
                    f.write(_nmrpaint_element_metadata(el,len(rendered.splitlines()))+"\n")
                    for _d in _internal_delay_metadata(el, rendered, fid_start):
                        f.write(";@NMRPAINT " + json.dumps(_d, separators=(",", ":"), ensure_ascii=False) + "\n")
                f.write(rendered+"\n")
            else:
                f.write(f"; unknown element type: {kind}\n")
                
        # -----------------------
        # multiple elements
        # -----------------------        
        else:
            centerable = {"pulse", "shaped"}
        
            center_parts = []
        
            pending_center_metadata=[]
            for e in els:
                kind=e.kind.lower()
                if kind in centerable:
                    text=write_center_element(e)
                    if text:
                        center_parts.append(text)
                        pending_center_metadata.append(e)
                else:
                    if center_parts:
                        if include_nmrpaint_metadata:
                            for ce in pending_center_metadata:
                                f.write(_nmrpaint_element_metadata(ce, 1) + "\n")
                        f.write(" (center " + " ".join(center_parts) + " )\n")
                        center_parts=[]
                        pending_center_metadata=[]
                    writer=ELEMENT_WRITERS.get(kind)
                    if writer:
                        rendered=writer(e)
                        if include_nmrpaint_metadata:
                            f.write(_nmrpaint_element_metadata(e, len(rendered.splitlines())) + "\n")
                            for _d in _internal_delay_metadata(e, rendered, fid_start):
                                f.write(";@NMRPAINT " + json.dumps(_d, separators=(",", ":"), ensure_ascii=False) + "\n")
                        f.write(rendered + "\n")
            if center_parts:
                if include_nmrpaint_metadata:
                    for ce in pending_center_metadata:
                        f.write(_nmrpaint_element_metadata(ce, 1) + "\n")
                f.write(" (center " + " ".join(center_parts) + " )\n")

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
    
            if exp_2d_option.value != "":
    
                phase_sensitive = ["States", "TPPI", "States-TPPI"]
    
                if exp_2d_option.value in phase_sensitive:
                        
                    calph_parts = []
                    
                    for row in pulse_dropdowns:
                    
                        phase = row["phase"].value
                    
                        if not phase:
                            continue
                    
                        inc = row["inc"].value
                    
                        calph_parts.append(
                            f"calph({phase}, {inc})"
                        )
                    
                    calph_string = " & ".join(calph_parts)
    
                    f.write(
                        f" 30m mc #0 to 2 "
                        f"F1PH({calph_string}, caldel(d0, +in0))\n"
                    )
    
                elif exp_2d_option.value == "Echo-Antiecho":
                    calph_parts = []
                    
                    for row in pulse_dropdowns:
                    
                        phase = row["phase"].value
                    
                        if not phase:
                            continue
                    
                        inc = row["inc"].value
                    
                        calph_parts.append(
                            f"calph({phase}, {inc})"
                        )
                    
                    calph_string = " & ".join(calph_parts)
                    selected = []

                    for row in shape_dropdowns:
                    
                        gp = row["gp"].value
                    
                        if not gp:
                            continue
                    
                        sign = row["sign"].value
                    
                        selected.append((gp, sign))
                    
                    ea_map = {}
                    
                    multiple = len(selected) > 1
                    
                    for i, (gp, sign) in enumerate(selected, start=1):
                    
                        suffix = f"EA{i}" if multiple else "EA"
                    
                        if sign == "+":
                            ea_map[gp] = suffix
                        else:
                            ea_map[gp] = f"*-1*{suffix}"
    
                    calea_parts = []
                    
                    for i in range(len(selected)):
                    
                        if len(selected) == 1:
                            calea_parts.append("calgrad(EA)")
                        else:
                            calea_parts.append(f"calgrad(EA{i+1})")
                    
                    calea_string = " & ".join(calea_parts)
                    delay_arg = "caldel(d0, +in0)"
                    
                    if calph_string:
                        delay_arg += f" & {calph_string}"
                    
                    f.write(
                        f" 30m mc #0 to 2 "
                        f"F1EA({calea_string}, {delay_arg})\n"
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
            if el.power
            and re.match(r"^pl\d+$", el.power.strip(), re.IGNORECASE)
        }
        | {
            p for p in cpd_powers
            if re.match(r"^pl\d+$", p, re.IGNORECASE)
        }
    )
    
    unique_pulses = sorted({
        el.name.strip()
        for el in sequence.elements
        if el.kind.lower() in ["pulse", "shaped", "block"]
        and el.name.strip()
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
    
    # -----------------------
    # Custom descriptions
    # -----------------------
    pulse_descriptions = {}
    delay_descriptions = {}
    shape_descriptions = {}
    
    for el in sequence.elements:
    
        description = getattr(el, "description", "").strip()
    
        if not description:
            continue
    
        kind = el.kind.lower()
    
        if kind in ["pulse", "shaped", "block"] and el.name.strip():
            pulse_descriptions.setdefault(
                el.name.strip(),
                description,
            )
    
        elif kind == "delay" and el.name.strip():
            delay_descriptions.setdefault(
                el.name.strip(),
                description,
            )
    
        elif getattr(el, "shape", None):
            shape_descriptions.setdefault(
                el.shape.strip(),
                description,
            )
            
    # -----------------------
    # Power definitions
    # -----------------------
    for pl in unique_power:
        explanation = power_defs.get(pl, "undefined")
        f.write(f";{pl}: {explanation}\n")
    
    f.write("\n")
    
    # -----------------------
    # Shape definitions
    # -----------------------
    
    for s in unique_shapes:
        explanation = shape_descriptions.get(
            s,
            shape_defs.get(s, "undefined"),
        )
    
        f.write(f";{s}: {explanation}\n")
    
    f.write("\n")
    
    
    # -----------------------
    # Pulse definitions
    # -----------------------
    
    for p in unique_pulses:
        explanation = pulse_descriptions.get(
            p,
            pulse_defs.get(p, "undefined"),
        )
    
        f.write(f";{p}: {explanation}\n")
    
    f.write("\n")
    
    
    # -----------------------
    # Delay definitions
    # -----------------------
    
    for d in unique_delays:
        explanation = delay_descriptions.get(
            d,
            delay_defs.get(d, "undefined"),
        )
    
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
    # Wavemaker statement
    # -----------------------
    
    if any(
        el.kind.lower() == "shaped" and getattr(el, "wvm", False)
        for el in sequence.elements
    ):
        f.write(";use AU-program proc_reset to process data\n")
        f.write(";run wvm -q before zg or launch with xaua\n\n")
        
    # -----------------------
    # Footer
    # -----------------------
    f.write(f";$Id: Generated using NMRpaint v{VERSION}$\n")

    return f.getvalue()
    
    # ------------------------------------------
    # ----- End of Pulse Program Generator -----
    # ------------------------------------------

# -----------------------------------------------#
# Print pulse program and generate download link #
# -----------------------------------------------#

def save_pulse_program(
    filename: str | Path,
    content: str,
) -> Path:
    """Save pulse-program text to an explicit local path."""
    return write_text_file(
        path=filename,
        content=content,
    )

def generate_current_pulse_program():
    """Generate the current pulse program text and filename."""

    populate_phase_rows()

    if phase_cycle_checkbox.value:
        generate_phase_cycle()

    content = build_pulse_program_text()

    filename = normalize_output_filename(
        exp_title.value,
        default="pulse_program",
    )

    return content, filename

def generate_program(b):
    browser_download_link.value = ""
    
    try:
        content, filename = generate_current_pulse_program()
        
        pulse_program_output.value = content
        
        output_path = save_pulse_program(
            filename=filename,
            content=content,
        )
        
        href = build_text_download_href(content)
        
        browser_download_link.value = f"""
        <a href="{href}"
           download="{filename}"
           style="
              display:inline-block;
              background:#eea236;
              color:white;
              padding:0px 20px;
              border-radius:2px;
              text-decoration:none;
              font-family:Arial, sans-serif;
           ">
           Download
        </a>
        """
        
        #print(f"Saved to: {output_path.resolve()}")
    
    except Exception as exc:
        generation_output.layout.display = "block"
        generation_output.clear_output(wait=True)
    
        with generation_output:
            print(f"Generation failed: {type(exc).__name__}: {exc}")
            
    draw_ctp()

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
    
# ----------------------------------
# Print pulse program next to canvas
# ----------------------------------
pulse_program_output = Textarea(
    value="",
    description="",
    layout=Layout(
        width="400px",
        height="410px"
    )
)

pulse_program_metadata_output = Textarea(
    value="",
    description="",
    layout=Layout(
        width="400px",
        height="410px",
        display="none"
    )
)

show_metadata_toggle = ToggleButton(
    value=False,
    description="Show NMRpaint metadata",
    tooltip="Show the internal ;@NMRPAINT conversion data used for exact Canvas ↔ Text round-tripping.",
    layout=Layout(width="400px", height="30px")
)

def _toggle_metadata(change):
    showing = bool(change["new"])
    pulse_program_output.layout.display = "none" if showing else "block"
    pulse_program_metadata_output.layout.display = "block" if showing else "none"
    show_metadata_toggle.description = "Hide NMRpaint metadata" if showing else "Show NMRpaint metadata"

show_metadata_toggle.observe(_toggle_metadata, names="value")

pulse_program_header = HTML("""
<div style="
    text-align:center;
    font-size:15px;
    font-weight:bold;
">
    Pulse program
</div>
""")

excluded_lines_selector=SelectMultiple(options=[],value=(),description="Exclude:",rows=5,layout=Layout(width="400px",height="115px"),style={"description_width":"55px"})

# -----------------------
# Phase Cycle GUI
# -----------------------

phase_rows = []

PHASE_MAP = {
    "x": 0,
    "y": 1,
    "-x": 2,
    "-y": 3
}

# Column widths — use these everywhere
W_LABEL = "120px"
W_DROPDOWN = "60px"
W_TEXT = "60px"
W_USE = "60px"

def centered_label(text, width):
    return HTML(
        f'<div style="width:{width}; text-align:center;">{text}</div>'
    )


phase_cycle_header = HBox([
    HTML(f'<div style="width:{W_LABEL};"></div>'),

    centered_label("φ", W_DROPDOWN),
    centered_label("= Δp", W_TEXT),
    centered_label("≠ Δp", W_TEXT),
    centered_label("Use", W_USE)
])

phase_cycle_container = VBox([])
phase_cycle_output = Textarea(
    layout=Layout(width="396px", height="160px")
)

def add_phase_row(el):

    pulse = el.name
    phase = el.phase

    include = Checkbox(
        value=False,
        indent=False,
        layout=Layout(width="20px")
    )

    include_container = HBox(
        [include],
        layout=Layout(
            width=W_USE,
            justify_content="center"
        )
    )

    nominal = Dropdown(
        options=["x", "y", "-x", "-y"],
        value="x",
        layout=Layout(width=W_DROPDOWN)
    )

    delta = Text(
        value="0",
        layout=Layout(width=W_TEXT)
    )

    disallowed = Text(
        value="",
        layout=Layout(width=W_TEXT)
    )

    label = Label(
        f"{pulse}:{phase}",
        layout=Layout(width=W_LABEL)
    )

    row_widget = HBox([
        label,
        nominal,
        delta,
        disallowed,
        include_container
    ])

    row_data = {
        "element": el,       # <-- identity of this particular pulse
        "include": include,
        "pulse": pulse,
        "phase": phase,
        "nominal": nominal,
        "delta": delta,
        "disallowed": disallowed,
        "label": label,
        "widget": row_widget
    }

    phase_rows.append(row_data)

    phase_cycle_container.children = (
        list(phase_cycle_container.children) + [row_widget]
    )

phase_cycle_title = HTML("""
<div style="
    text-align:center;
    font-size:15px;
    font-weight:bold;
">
    Phase Cycle Generator
</div>
""")

phase_cycle_box = VBox([
    phase_cycle_title,
    phase_cycle_header,
    phase_cycle_container,
    phase_cycle_output
])

phase_cycle_box.layout = Layout(
    width="400px",
    margin="50px 0 0 0"
)

def populate_phase_rows():

    # All phase-cycling elements, in their order of appearance
    sequence_elements = [
        el for el in sequence.elements
        if el.phase and el.phase.startswith("ph")
    ]

    # Existing rows indexed by the actual SequenceElement
    existing_rows = {
        id(row["element"]): row
        for row in phase_rows
    }

    new_phase_rows = []

    for el in sequence_elements:

        key = id(el)

        if key in existing_rows:

            # Existing row: update its information
            row = existing_rows[key]

            row["element"] = el
            row["pulse"] = el.name
            row["phase"] = el.phase

            row["label"].value = f"{el.name}:{el.phase}"

            new_phase_rows.append(row)

        else:

            # New element: create a new row
            add_phase_row(el)

            new_phase_rows.append(phase_rows[-1])

    # Replace phase_rows with the rows that still exist
    phase_rows[:] = new_phase_rows

    # Display them in exactly the same order as sequence.elements
    phase_cycle_container.children = tuple(
        row["widget"]
        for row in phase_rows
    )
    
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
    
#------------------------------------------------
# Make sure the requested phase cycle is physical
#------------------------------------------------

def validate_phase_cycle():

    phase_deltas = {}

    for row in phase_rows:

        if not row["include"].value:
            continue

        phase = row["phase"]

        try:
            delta = int(row["delta"].value)
        except (ValueError, TypeError):
            continue

        phase_deltas.setdefault(phase, set()).add(delta)

    conflicts = {
        phase: deltas
        for phase, deltas in phase_deltas.items()
        if len(deltas) > 1
    }

    if conflicts:
        messages = []

        for phase, deltas in conflicts.items():

            delta_string = ", ".join(
                f"{d:+d}" for d in sorted(deltas)
            )

            messages.append(
                f"⚠ Warning: {phase} is assigned different Δp values "
                f"({delta_string}) among included pulses."
            )

        return False, "\n".join(messages)

    return True, ""


#----------------------
# Generate phase cycle
#----------------------

def generate_phase_cycle():

    # Validate BEFORE doing anything else
    valid, message = validate_phase_cycle()

    if not valid:
        phase_cycle_output.value = message
        return

    included = []
    excluded = []

    for r in phase_rows:

        delta = int(r["delta"].value)

        row = {
            "phase": r["phase"],
            "delta": delta,
            "nominal": PHASE_MAP[r["nominal"].value],
            "disallowed": r["disallowed"].value.strip()
        }

        if r["include"].value:
            included.append(row)
        else:
            excluded.append(row)

    # sort phases numerically (ph1, ph2, ph3, ...)
    included.sort(
        key=lambda r: int(r["phase"][2:])
    )

    excluded.sort(
        key=lambda r: int(r["phase"][2:])
    )

    if not included:

        cols = 1
        tableC = {}

        for row in excluded:
            tableC[row["phase"]] = [row["nominal"]]

        ph31 = [0]

    else:

        bases = [
            determine_steps(
                r["delta"],
                r["disallowed"]
            )
            for r in included
        ]

        print("base_steps per phase =", bases)

        # ---- nested cycle
        cycles = nested_cycles(bases)

        tableA = {}

        for i, row in enumerate(included):
            tableA[row["phase"]] = cycles[i]

        cols = len(cycles[0])

        # ---- Table C
        tableC = {}

        # included phases
        for r, row in enumerate(included):

            vals = tableA[row["phase"]]
            nominal = row["nominal"]

            tableC[row["phase"]] = [
                (v + nominal) % 4
                for v in vals
            ]

        # phases excluded from the nested cycle
        for row in excluded:

            tableC[row["phase"]] = [
                row["nominal"]
            ] * cols

        # ---- Table B (receiver)
        ph31 = []

        for c in range(cols):

            s = 0

            for row in phase_rows:

                phase = tableC[row["phase"]][c]
                delta = int(row["delta"].value)

                s += phase * delta

            ph31.append(s % 4)

    # ---- Print result
    text = ";Phase table\n"

    for ph in sorted(
        tableC.keys(),
        key=lambda x: int(x[2:])
    ):

        v = tableC[ph]

        text += (
            f"{ph}={' '.join(map(str, v))}\n"
        )

    text += (
        "\nph31="
        + " ".join(map(str, ph31))
    )

    phase_cycle_output.value = text


# Pulse program GUI layout
pulse_program_box = VBox(
    [
        pulse_program_header,
        pulse_program_output,
        pulse_program_metadata_output,
        show_metadata_toggle,
        excluded_lines_selector,
        phase_cycle_box
    ],
    layout=Layout(padding='0px 20px')
)

pulse_program_box.layout.flex = "0 0 auto"

# -----------------------
# CTP logic
# -----------------------
sorted_elements_cache = []
sequence_dirty = True

def get_sorted_elements():
    global sorted_elements_cache, sequence_dirty

    if sequence_dirty:
        sorted_elements_cache = sorted(
            sequence.elements,
            key=lambda e: e.start
        )
        sequence_dirty = False

    return sorted_elements_cache
    
def get_ctp_events():

    events = []

    for el in get_sorted_elements():

        # Only RF pulses affect coherence
        if el.kind not in ("pulse", "shaped"):
            continue

        events.append({
            "name": el.name,
            "channel": el.channel,
            "phase": el.phase,
            "delta": get_phase_delta(el),
            "x0": el.start * timeline_scale,
            "x1": (el.start + el.duration) * timeline_scale,
            "width": el.visual_width,
            "kind": el.kind

        })

    return events

def draw_ctp():
    draw_ctp_background()

    c = ctp_canvas
    c.line_width = 5

    phase_delta_map = build_phase_delta_map()

    coherence = {
        "f1": 0,
        "f2": 0,
    }

    xpos = {
        "f1": 40,
        "f2": 40,
    }

    elements = get_sorted_elements()
    
    # Determine pathway colors
    final_coherence = {"f1": 0, "f2": 0}
    
    for el in elements:
    
        if el.kind not in ("pulse", "shaped"):
            continue
    
        if el.channel not in ("f1", "f2"):
            continue
    
        final_coherence[el.channel] += phase_delta_map.get(id(el), 0)
    
    channel_color = {
        "f1": "green" if final_coherence["f1"] == -1 else "red",
        "f2": "green"
    }
    
    for el in elements:

        if el.channel not in ("f1", "f2"):
            continue

        channel = el.channel
        c.stroke_style = channel_color[channel]
        c.line_cap = "round"
        levels = ctp_channel_positions[channel]
        current = coherence[channel]

        x0 = xpos[channel]
        xpulse = el.start * timeline_scale

        # horizontal before element
        if xpulse > x0:

            draw_ctp_horizontal(
                c,
                x0,
                xpulse,
                levels[current]
            )

        # ----------------------------
        # delay
        # ----------------------------
        if el.kind == "delay":

            xpos[channel] = (
                el.start + el.duration
            ) * timeline_scale

            draw_ctp_horizontal(
                c,
                xpulse,
                xpos[channel],
                levels[current]
            )

            continue

        # ----------------------------
        # pulse
        # ----------------------------
        if el.kind in ("pulse", "shaped"):

            delta = phase_delta_map.get(id(el), 0)

            new = max(-3, min(3, current + delta))

            x1 = (
                el.start + el.duration
            ) * timeline_scale

            draw_ctp_diagonal(
                c,
                xpulse,
                x1,
                levels[current],
                levels[new]
            )

            coherence[channel] = new
            xpos[channel] = x1

            continue

    # ---------------------------------------
    # Extend channels after the last pulse
    # ---------------------------------------
    
    fid_x = get_fid_start_time() * timeline_scale
    
    # ---------- F1 ----------
    c.stroke_style = channel_color["f1"]
    
    levels = ctp_channel_positions["f1"]
    
    if xpos["f1"] < fid_x:
    
        draw_ctp_horizontal(
            c,
            xpos["f1"],
            fid_x,
            levels[coherence["f1"]]
        )
    
    # ---------- F2 ----------
    c.stroke_style = channel_color["f2"]
    
    levels = ctp_channel_positions["f2"]
    
    draw_ctp_horizontal(
        c,
        xpos["f2"],
        c.width,
        levels[coherence["f2"]]
    )
    
    # ---------------------------------------
    # Draw acquisition (-1 coherence)
    # ---------------------------------------
    
    c.stroke_style = channel_color["f1"]
    
    levels = ctp_channel_positions["f1"]
    
    draw_ctp_horizontal(
        c,
        fid_x,
        c.width,
        levels[-1]
    )

# -----------------------
# Register Handlers
# -----------------------
delete_button.on_click(delete_selected_element)

undo_button.on_click(undo_last)
clear_button.on_click(clear_sequence)
toggle_delays_btn.on_click(toggle_delay_selection)
print_names_button._click_handlers.callbacks.clear()
print_names_button.on_click(generate_program)

browser_download_button._click_handlers.callbacks.clear()
browser_download_button.on_click(generate_program)

# -----------------------------------------
# Number of scans (ns) and dummy scans (ds)
# -----------------------------------------
ns_text = IntText(
    description="ns:",
    value=1,
    tooltip="",
    layout=Layout(width="100px"),
    style={'description_width': '30px'}
)

ds_text = IntText(
    description="ds:",
    value=0,
    tooltip="",
    layout=Layout(width="100px"),
    style={'description_width': '30px'}
)

# -------------------------
# Experiment Properties Row
# -------------------------
exp_title = Text(
    description="Title:",
    layout=Layout(width="220px", margin="0px"),
    style={'description_width': '40px'}
)

exp_dim = Dropdown(
    description="Dim:",
    options=["1D", "2D"],
    value="1D",
    layout=Layout(width="110px"),
    style={'description_width': '30px'}  # label width
)

exp_class = Dropdown(
    description="Class:",
    options=["HighRes", "HighRes HWT", "HighRes Incl"],
    value="HighRes",
    layout=Layout(width="160px"),  # total width
    style={'description_width': '40px'}  # label width
)

exp_2d_option = Dropdown(
    description="2D Option:",
    options=["", "States-TPPI", "QF", "Echo-Antiecho", "QF(no frequency)", "undefined", "States", "TPPI"],
    value=None,
    layout=Layout(width="220px")
)
exp_2d_option.layout.display = "none"

# ---------------------------
# Pulse dropdowns for 2D exps
# ---------------------------
pulse_dropdowns = []

pulse_section_label = Label(
    "Phase increment:",
    layout=Layout(width="100px", flex="0 0 auto")
)

pulse_dropdowns_container = HBox(
    [],
    layout=Layout(
        width="100%",
        flex="1 1 auto",
        align_items="stretch",
        margin="0px",
        padding="0px"
    )
)

pulse_section = HBox(
    [pulse_section_label, pulse_dropdowns_container],
    layout=Layout(
        width="100%",
        flex="1 1 auto",
        align_items="center",
        margin="0px",
        padding="0px",
        display="none"
    )
)

# shapes
shape_dropdowns = []

shape_section_label = Label(
    "EA increment:",
    layout=Layout(width="80px", flex="0 0 auto")
)

shape_dropdowns_container = HBox(
    [],
    layout=Layout(
        width="100%",
        flex="1 1 auto",
        align_items="stretch",
        margin="0px",
        padding="0px"
    )
)

shape_section = HBox(
    [shape_section_label, shape_dropdowns_container],
    layout=Layout(
        width="100%",
        flex="1 1 auto",
        align_items="center",
        margin="0px",
        padding="0px",
        display="none"
    )
)

def update_2d_dropdowns(change=None):

    if exp_dim.value != "2D":
        pulse_dropdowns.clear()
        shape_dropdowns.clear()

        pulse_dropdowns_container.children = ()
        shape_dropdowns_container.children = ()

        pulse_section.layout.display = "none"
        shape_section.layout.display = "none"
        return

    phase_sensitive = ["States", "TPPI", "States-TPPI"]

    # -----------------------------
    # Clear everything
    # -----------------------------
    pulse_dropdowns.clear()
    shape_dropdowns.clear()

    pulse_dropdowns_container.children = ()
    shape_dropdowns_container.children = ()

    pulse_section.layout.display = "none"
    shape_section.layout.display = "none"

    #---------------
    # Echo-Antiecho
    #---------------
    if exp_2d_option.value == "Echo-Antiecho":

        pulse_section.layout.display = "flex"
        shape_section.layout.display = "flex"

        # ----------------- Pulses -----------------
        phase_names = sorted({
            el.phase for el in sequence.elements
            if el.kind.lower() in ["pulse", "shaped"] and el.phase
        })
        
        phase_names = [
            p for p in phase_names
            if p != "ph31"
        ] + ["ph31"]

        def add_pulse_dropdown(change=None):

            if change is not None and not change["new"]:
                return

            phase_dd = Dropdown(
                options=[""] + phase_names,
                layout=Layout(width="90px")
            )
            
            inc_dd = Dropdown(
                options=["+90", "+180", "+270"],
                value="+90",
                layout=Layout(width="70px")
            )
            
            phase_dd.observe(add_pulse_dropdown, names="value")
            
            row = HBox(
                [phase_dd, inc_dd],
                layout=Layout(spacing="2px")
            )
            pulse_dropdowns.append({
                "phase": phase_dd,
                "inc": inc_dd,
                "widget": row,
            })

            pulse_dropdowns_container.children = tuple(
                r["widget"] for r in pulse_dropdowns
            )

        add_pulse_dropdown()

        # ----------------- Gradients -----------------
        gradients = sorted(
            [el for el in sequence.elements if el.kind.lower() == "grad"],
            key=lambda el: el.start
        )

        shape_names = [f"gp{i}" for i in range(1, len(gradients)+1)]

        def add_shape_dropdown(change=None):

            if change is not None and not change["new"]:
                return

            gp_dd = Dropdown(
                options=[""] + shape_names,
                layout=Layout(width="90px")
            )
            
            sign_dd = Dropdown(
                options=["+", "-"],
                value="+",
                layout=Layout(width="60px")
            )
            
            gp_dd.observe(add_shape_dropdown, names="value")
            
            row = HBox(
                [gp_dd, sign_dd],
                layout=Layout(space="2px")
            )
            
            shape_dropdowns.append({
                "gp": gp_dd,
                "sign": sign_dd,
                "widget": row,
            })

            shape_dropdowns_container.children = tuple(
                r["widget"] for r in shape_dropdowns
            )

        add_shape_dropdown()

        return

    # ======================================================
    # States / TPPI / States-TPPI
    # ======================================================
    if exp_2d_option.value in phase_sensitive:

        pulse_section.layout.display = "flex"

        phase_names = sorted({
            el.phase for el in sequence.elements
            if el.kind.lower() in ["pulse", "shaped"] and el.phase
        })
        
        phase_names = [
            p for p in phase_names
            if p != "ph31"
        ] + ["ph31"]
        
        def add_pulse_dropdown(change=None):

            if change is not None and not change["new"]:
                return

            phase_dd = Dropdown(
                options=[""] + phase_names,
                layout=Layout(width="90px")
            )

            inc_dd = Dropdown(
                options=["+90", "+180", "+270"],
                value="+90",
                layout=Layout(width="70px")
            )

            phase_dd.observe(add_pulse_dropdown, names="value")

            row = HBox(
                [phase_dd, inc_dd],
                layout=Layout(spacing="2px")
            )

            pulse_dropdowns.append({
                "phase": phase_dd,
                "inc": inc_dd,
                "widget": row,
            })

            pulse_dropdowns_container.children = tuple(
                r["widget"] for r in pulse_dropdowns
            )

        add_pulse_dropdown()
        
#----------
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
        exp_2d_option.value = None

    update_2d_dropdowns()

exp_dim.observe(on_dim_change, names="value")


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

definitions_header = HTML("""
<div style="
    text-align:center;
    font-size:15px;
    font-weight:bold;
    padding-top:10px;
">
    Global definitions
</div>
""")

update_button = Button(
    description="Update Element",
    button_style="success",
    tooltip="Update Element"
)

update_button.layout = Layout(
    margin="10px auto 0px auto"
)


property_editor_content = VBox(
    layout=Layout(width="100%")
)

property_editor_box = VBox(
    [
        property_editor_header,
        property_editor_content,
        update_button,
        definitions_header,
        definitions_text
    ]
)

property_editor_box.layout.flex = "0 0 auto"

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
    description="Definition",
    layout=field_layout,
    style=label_style
)

el_description = Text(
    description="Description",
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
    tooltip="",
    layout=field_layout,
    style=label_style
)

el_height = IntText(
    description="Height",
    tooltip="",
    layout=field_layout,
    style=label_style
)

#---------------------------------
# Initialize content on start up
#---------------------------------
property_editor_content.children = (
    el_title,
    el_name,
    el_definition,
    el_description,
    el_shape,
    el_channel,
    el_power,
    el_phase,
    el_duration,
    el_height,
    wvm_box
)

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
    el_description.value = getattr(el, "description", "") or ""
    el_shape.value = getattr(el, "shape", "") or ""

    el_channel.value = getattr(el, "channel", "f1") or "f1"

    el_power.value = getattr(el, "power", "") or ""
    el_phase.value = getattr(el, "phase", "") or ""

    el_duration.value = getattr(el, "duration", 0)

    if hasattr(el, "visual_height"):
        el_height.value = el.visual_height
    
    el_wvm.value = getattr(el, "wvm", False)
    
    el_powerindex.value = getattr(el, "powerindex", "")
    el_subname.value = getattr(el, "subname", "")
    el_length.value = getattr(el, "length", "")
    el_stepsize.value = getattr(el, "stepsize", "")
    el_bandwidth.value = getattr(el, "bandwidth", "")
    el_Q.value = getattr(el, "Q", "")
    el_sweepdirection.value = getattr(el, "sweepdirection", "")
    
    update_wvm_visibility(None)
   
    # ---------------------------
    # Build editor layout
    # ---------------------------

    if kind == "pulse":

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_description,
            el_channel,
            el_power,
            el_phase,
            el_duration,
            el_height
        ]

    elif kind == "shaped":

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_description,
            el_shape,
            el_channel,
            el_power,
            el_phase,
            el_duration,
            el_height,
            el_wvm,
            wvm_box
        ]

    elif kind == "grad":

        visible_widgets = [
            el_title,
            el_name,
            el_description,
            el_channel,
            el_power,
            el_duration,
            el_height
        ]

    elif kind == "cpd":

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_channel,
            el_power,
            el_duration,
            el_height
        ]

    elif kind == "flag":

        visible_widgets = [
            el_definition
        ]

    elif kind == "block":

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_channel,
            el_duration,
            el_height
        ]

    elif kind == "delay":

        visible_widgets = [
            el_name,
            el_definition,
            el_description,
            el_duration
        ]

    else:

        visible_widgets = [
            el_title,
            el_name,
            el_definition,
            el_description,
            el_channel,
            el_duration
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
        el.description = el_description.value
    
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
    
            # ---------------------------
            # WVM properties
            # ---------------------------
            el.wvm = el_wvm.value
            el.powerindex = el_powerindex.value
            el.subname = el_subname.value
            el.length = el_length.value
            el.stepsize = el_stepsize.value
            el.bandwidth = el_bandwidth.value
            el.Q = el_Q.value
            el.sweepdirection = el_sweepdirection.value
    
        if kind in ["pulse", "shaped", "block", "grad"]:
            el.visual_height = el_height.value
    
        if kind == "delay":
            el.manual = True
    
        if el.kind != "delay":
            rebuild_global_delays()
            
        refresh_ui()
    
        populate_phase_rows()
        generate_phase_cycle()
    
    update_button._click_handlers.callbacks.clear()
    update_button.on_click(update_el)
    update_button.on_click(generate_program)
    
# -----------------------
# Main canvas Setup
# -----------------------

canvas_width = 900
canvas_height = 410

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
# CTP canvas setup
# -----------------------
ctp_canvas_height = canvas_height

ctp_canvas = Canvas(
    width=canvas_width,
    height=ctp_canvas_height,
    sync_image_data=False
)

ctp_dynamic_canvas = Canvas(
    width=canvas_width,
    height=ctp_canvas_height,
    sync_image_data=False
)

for c in (ctp_canvas, ctp_dynamic_canvas):
    c.layout.position = "absolute"
    c.layout.left = "0px"
    c.layout.top = "0px"
    c.layout.width = f"{canvas_width}px"
    c.layout.height = f"{ctp_canvas_height}px"

ctp_dynamic_canvas.layout.pointer_events = "none"

ctp_canvas.layout.border = "1px solid black"

ctp_container = Box(
    children=[ctp_canvas, ctp_dynamic_canvas],
    layout=Layout(
        position="relative",
        width=f"{canvas_width}px",
        height=f"{ctp_canvas_height}px",
        display="block",
        overflow="hidden",
    )
)

ctp_box = ctp_container

def draw_ctp_background():

    c = ctp_canvas

    c.clear()

    c.fill_style = "white"
    c.fill_rect(0, 0, c.width, c.height)

    c.font = "15px Arial"

    # vertical reference line
    c.stroke_style = "black"
    c.line_width = 1
    c.set_line_dash([6,6])
    c.stroke_line(40, 0, 40, c.height)
    c.set_line_dash([])

    for channel in ["f1", "f2"]:

        levels = ctp_channel_positions[channel]

        # Channel label
        c.fill_style = "black"
        c.font = "18px Arial"
        c.text_align = "left"
        c.text_baseline = "middle"
        c.fill_text(channel.upper(), 55, levels[3])

        for coherence, y in sorted(levels.items(), reverse=True):

            if coherence == 0:
                c.stroke_style = "black"
                c.line_width = 2
                c.set_line_dash([])
            else:
                c.stroke_style = "#BFBFBF"
                c.line_width = 1
                c.set_line_dash([8,6])

            c.stroke_line(0, y, c.width, y)

            c.fill_style = "black"
            c.font = "15px Arial"
            c.text_align = "center"
            c.text_baseline = "middle"
            c.fill_text(str(coherence), 18, y)

    c.set_line_dash([])
    
draw_ctp_background()

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

    ctp_canvas.width = canvas_width
    ctp_dynamic_canvas.width = canvas_width
    
    for c in (canvas, dynamic_canvas):
        c.layout.width = f"{canvas_width}px"
        c.layout.height = f"{canvas_height}px"
    
    for c in (ctp_canvas, ctp_dynamic_canvas):
        c.layout.width = f"{canvas_width}px"
        c.layout.height = f"{ctp_canvas_height}px"

    canvas_container.layout.width = f"{canvas_width}px"
    canvas_container.layout.height = f"{canvas_height}px"
    canvas_container.layout.min_width  = f"{canvas_width}px"
    canvas_container.layout.min_height = f"{canvas_height}px"
    
    canvas_container.layout.overflow_x = "hidden"
    canvas_container.layout.overflow_y = "visible"
    canvas_container.layout.align_items = "center"
    canvas_container.layout.box_sizing = "border-box"

    ctp_container.layout.width = f"{canvas_width}px"
    ctp_container.layout.height = f"{ctp_canvas_height}px"
    ctp_container.layout.min_width = f"{canvas_width}px"
    ctp_container.layout.min_height = f"{ctp_canvas_height}px"
    
    ctp_container.layout.overflow_x = "hidden"
    ctp_container.layout.overflow_y = "visible"
    ctp_container.layout.align_items = "center"
    ctp_container.layout.box_sizing = "border-box"

    canvas_section.layout.width = f"{canvas_width}px"
    canvas_section.layout.min_width = f"{canvas_width}px"
    
    ctp_section.layout.width = f"{canvas_width}px"
    ctp_section.layout.min_width = f"{canvas_width}px"
    
    canvas_box.layout.width = f"{canvas_width}px"
    canvas_box.layout.min_width = f"{canvas_width}px"
    
    ctp_box.layout.width = f"{canvas_width}px"
    ctp_box.layout.min_width = f"{canvas_width}px"

    rebuild_global_delays()
    draw_ctp_background()
    refresh_ui()
    
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

    
# -----------------------
# Element Button
# -----------------------
def create_element_button(kind, file_path):

    base = resource_filename(file_path).lower()

    # --- Display names ---
    display_names = {
        "p0.txt": "var",
        "p90.txt": "90",
        "p180.txt": "180",
        "sp1.txt": "sel. pulse",
        "gp1.txt": "gradient",
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
    for el in get_sorted_elements():
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

def refresh_ui():
    draw_sequence()
    draw_ctp()
    coherence_label.value = sequence.coherence_summary()
    
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

elements_section.layout.flex = "0 0 auto"
property_editor_box.layout.flex = "0 0 250px"

# -----------------------
# Canvas + Coherence
# -----------------------

# Canvas size controls
canvas_width_input = IntText(
    description="Canvas width:",
    value=canvas_width,
    tooltip="",
    layout=Layout(width="170px"),
    style={'description_width': '80px'}
)

apply_canvas_size_btn = Button(
    description="Update",
    button_style="info",
    tooltip="Resize canvas"
)

def on_apply_canvas_size(_):
    set_canvas_size(canvas_width_input.value, canvas_height)

apply_canvas_size_btn.on_click(on_apply_canvas_size)

coherence_label = Label(
    value=sequence.coherence_summary()
)

canvas_row = HBox(
    [
        canvas_width_input,
        apply_canvas_size_btn,
        canvas_download_link,
        coherence_label
    ],
    layout=Layout(
        spacing='10px',
        padding='0px 0px'
    )
)

#export_btn

ctp_section = VBox([
    HTML("""
    <div style="
        text-align:center;
        font-size:15px;
        font-weight:bold;
    ">
        &nbsp;
    </div>
    """),
    ctp_box
])

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
    canvas_row,
    ctp_section
])

canvas_section.layout.width = f"{canvas_width}px"
canvas_section.layout.flex = "0 0 auto"

canvas_container.layout.flex = "0 0 auto"
canvas_container.layout.width  = f"{canvas_width}px"
canvas_container.layout.height = f"{canvas_height}px"
canvas_container.layout.overflow = "hidden"
#canvas_container.layout.align_items = "center"

canvas_box.layout.flex = "0 0 auto"

ctp_section.layout.flex = "0 0 auto"
ctp_box.layout.flex = "0 0 auto"

# -----------------------
# Mouse actions
# -----------------------
# Temporary state during drag
drag_temp_start = 0
drag_temp_width = 0
drag_temp_height = 0

def on_canvas_mouse_down(x, y):
    global sequence_dirty
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

            draw_ctp()
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
    sequence_dirty = True
    rebuild_global_delays()
    refresh_ui()
    
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
    global sequence_dirty
    global dragging_el, drag_mode, drag_temp_start, drag_temp_width, drag_temp_height

    if not dragging_el:
        return

    save_state()

    pulse_unit = 2
    dragging_el.start = round(drag_temp_start / pulse_unit) * pulse_unit
    sequence_dirty = True
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

    dragging_el = None
    drag_mode = None

    dynamic_canvas.clear()
    refresh_ui()
    
canvas.on_mouse_down(on_canvas_mouse_down)
canvas.on_mouse_move(on_canvas_mouse_move)
canvas.on_mouse_up(on_canvas_mouse_up)

# -----------------------
# Buttons row
# -----------------------

buttons_row = HBox(
    [
        clear_button,
        undo_button,
        delete_button,
        toggle_delays_btn,
        browser_download_link,
        phase_cycle_checkbox
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
# Canvas <-> text conversion controls
# -----------------------
canvas_to_text_button=Button(description="→",tooltip="Convert canvas to pulse-program text",layout=Layout(width="34px",height="34px",padding="0px"))
text_to_canvas_button=Button(description="←",tooltip="Convert pulse-program text to canvas",layout=Layout(width="34px",height="34px",padding="0px"))
conversion_buttons=VBox([canvas_to_text_button,text_to_canvas_button],layout=Layout(width="40px",align_items="center",justify_content="center",gap="6px",padding="0px"))
canvas_to_text_button.on_click(canvas_to_text); text_to_canvas_button.on_click(text_to_canvas); pulse_program_output.observe(update_excluded_line_options,names="value")

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

canvas_scroll_box = Box(
    children=[canvas_section],
    layout=Layout(
        width="900px",
        overflow_x="auto",
        overflow_y="hidden"
    )
)

canvas_scroll_box.layout.min_width = "0px"

main_top_row = HBox(
    [
        elements_section,
        canvas_scroll_box,
        conversion_buttons,
        pulse_program_box,
        property_editor_box
    ],
    layout=Layout(
        justify_content="flex-start",
        gap="10px"
    )
)

main_top_row.layout.flex_wrap = "nowrap"

exp_prop_row_1 = HBox(
    [exp_title, exp_dim],
    layout=Layout(
        spacing="1px",
        align_items="center"
    ),
    padding='20px 20px'
)

exp_prop_row_2 = HBox(
    [exp_2d_option, pulse_section, shape_section],
    layout=Layout(spacing="1px"),
    padding='20px 20px' 
)

exp_prop_row_3 = HBox(
    [exp_class, exp_type, exp_subtype, exp_incl, ns_text, ds_text, exp_comment],
    layout=Layout(spacing="1px"),
    padding='20px 20px' 
)

exp_prop_section = VBox([
    exp_prop_row_1,
    exp_prop_row_2,
    exp_prop_row_3
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
    padding-bottom:10px;">
    NMR
</span>p<span style="
    display:inline-block;
    border-bottom:5px solid #BC4B00;
    padding-bottom:10px;
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
<style>
#nmrpaint-background {
    position: fixed;
    inset: 0;
    min-height: 100dvh;
    background: #EDF1F9;
    z-index: -1;
}
</style>

<div id="nmrpaint-background"></div>
""")

app_wrapper.layout = Layout(
    width="0px",
    height="0px",
)

background = HTML("""
<style>
body {
    background: #EDF1F9 !important;
}

div.jp-OutputArea-output {
    background: #EDF1F9 !important;
}
</style>
""")

main_vbox = VBox(
    [
        background,
        app_title,
        top_bar,
        exp_prop_section,
        generation_output,
        main_top_row,
        copyright_footer,
    ],
    layout=Layout(
        width="100%",
        height="100%",
        overflow="hidden"
    ),
)

main_vbox.layout.z_index = "1"
main_vbox.layout.overflow = "hidden"
main_top_row.layout = Layout(
    width="100%",
    flex="1 1 auto",
)
main_top_row.layout.width = "100%"
main_top_row.layout.overflow = "hidden"

copyright_footer.layout = Layout(
    flex="0 0 auto",
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

def create_app():
    """Return the complete NMRpaint widget application."""

    display(HTML("""
    <style>


    body,
    #jp-main-content-panel,
    #rendered_cells {
        background: #EDF1F9 !important;
    }
    </style>
    """))

    return main_vbox

sequence.add(delay)
draw_sequence()
draw_ctp()

if __name__ == "__main__":
    display(create_app())
