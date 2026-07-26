# NMRpaint Repository Handover Guide

This guide is for transferring NMRpaint to the original author or a new
maintainer who has little or no Git or GitHub experience.

The recommended workflow uses the GitHub website and the `github.dev` browser
editor. Command-line Git is not required for routine maintenance.

---

## 1. Handover Goal

The handover is complete when the new maintainer can:

1. locate the maintained source code;
2. edit a file through GitHub;
3. create a branch and pull request;
4. merge an approved change into `main`;
5. read a GitHub Actions result;
6. confirm that the Voici web application was deployed;
7. create a release; and
8. recover from a failed update without deleting repository history.

---

## 2. Files the New Maintainer Must Know

### Maintained application source

```text
src/nmrpaint/app.py
```

This is the primary source file for the GUI, canvas, callbacks, application
state, and pulse-program generation.

### Supporting source

```text
src/nmrpaint/exporters.py
src/nmrpaint/resource_manager.py
src/nmrpaint/resources/
tests/
```

### Launchers

```text
apps/NMRpaint_local.ipynb
voici/content/NMRpaint.ipynb
```

The notebooks are launchers only. Application logic must remain under
`src/nmrpaint/`.

### Deployment

```text
.github/workflows/deploy-voici.yml
```

### Legal and citation files

```text
LICENSE
NOTICE
CITATION.cff
AUTHORS.md
```

### Generated files that must not be edited

```text
build/
dist/
output/
voici/_output/
voici/pypi/*.whl
```

Developer and maintenance instructions are in:

```text
README.md
```

---

## 3. Information to Complete Before Public Release

Replace the remaining placeholders in the repository:

```text
[COPYRIGHT_HOLDER]
[ORIGINAL_AUTHOR_FULL_NAME]
[CONTACT_EMAIL]
[FIRST_PUBLICATION_YEAR]
[REPOSITORY_URL]
[WEB_APP_URL]
PLACEHOLDER_GIVEN_NAMES
PLACEHOLDER_FAMILY_NAME
```

Also verify:

- the original author's ORCID;
- the final repository URL;
- the final GitHub Pages URL;
- the software version;
- the release date; and
- the preferred scientific citation, when available.

Do not search for a single `[` character. Markdown files contain many normal
links and brackets. Search for `PLACEHOLDER` and the exact placeholder names
listed above.

---

## 4. Recommended Two-Stage Transfer

### Stage A — Assisted maintenance

Before transferring ownership:

1. invite the original author as a collaborator;
2. ask them to complete one documentation change;
3. ask them to complete one small application change;
4. review both changes through pull requests;
5. confirm that GitHub Actions and deployment succeed; and
6. keep the current owner available for support.

One or two successful update cycles are normally sufficient.

### Stage B — Ownership transfer

After the new maintainer is comfortable:

1. transfer repository ownership;
2. keep the previous owner as a collaborator;
3. rerun the GitHub Pages workflow;
4. confirm the new repository and Pages URLs;
5. update the URLs in project documentation; and
6. create a post-transfer release.

---

## 5. Invite the New Maintainer

The current owner should open:

```text
Repository → Settings → Collaborators → Add people
```

Enter the new maintainer's GitHub username or email address.

The new maintainer must accept the invitation.

Do not transfer ownership immediately. First confirm that the collaborator can
edit files, create pull requests, review changes, and verify deployment.

---

## 6. First GitHub Exercise

Use a low-risk documentation edit.

1. Open the repository on GitHub.
2. Open `README.md`.
3. Press the `.` key to open `github.dev`.
4. Add or correct one sentence.
5. Save the file.
6. Open **Source Control**.
7. create a new branch, for example:

   ```text
   docs-handover-test
   ```

8. Commit with:

   ```text
   Test repository handover workflow
   ```

9. Create a pull request against `main`.
10. Review and merge the pull request.
11. Open **Actions** and confirm that the workflow is green.
12. Open the deployed web application and confirm that it still loads.

This exercise tests the complete edit-review-deploy workflow without changing
application behavior.

---

## 7. Editing with github.dev

From the repository page, press:

```text
.
```

The repository opens in the browser-based `github.dev` editor.

Use:

```text
Ctrl+S
```

to save files.

For an inexperienced maintainer, use a new branch and pull request instead of
committing directly to `main`.

The browser editor does not run the Python tests or build Voici locally.
Automated validation is performed by GitHub Actions.

Uncommitted work is stored in browser storage. Commit regularly.

---

## 8. Standard Change Workflow

For each logical change:

1. create a dedicated branch;
2. edit the appropriate source file;
3. save the changes;
4. write a specific commit message;
5. create a pull request against `main`;
6. review the changed files;
7. wait for automated checks;
8. merge only after required checks pass;
9. confirm the deployment workflow on `main`; and
10. test the deployed application in a private browser window.

Example branch names:

```text
fix-gradient-label
add-pulse-property
update-cpd-resource
docs-update-license-contact
release-0.2.0
```

Do not edit generated files or move application logic into the launcher
notebooks.

---

## 9. Reading GitHub Actions

Open:

```text
Repository → Actions
```

The production workflow is:

```text
Deploy NMRpaint Voici
```

A successful run should show green checks for testing, building, and
deployment.

If a run fails:

1. open the failed workflow;
2. open the first failed job;
3. expand the first red step;
4. copy the final error section;
5. compare the failure with the last successful run; and
6. do not change dependency versions repeatedly without diagnosis.

A failed new deployment normally leaves the last successful website available.

---

## 10. Transfer Repository Ownership

When the new maintainer is ready, the current owner should open:

```text
Repository → Settings → General → Danger Zone → Transfer
```

Enter:

- the new owner's GitHub username; and
- the repository name exactly as requested by GitHub.

The recipient must accept the transfer.

After transfer:

1. confirm that the previous owner remains a collaborator;
2. open **Settings → Pages**;
3. confirm that the source is **GitHub Actions**;
4. open **Actions → Deploy NMRpaint Voici**;
5. run the workflow on `main`;
6. confirm the new GitHub Pages URL; and
7. update repository and website URLs in:
   - `README.md`;
   - `CITATION.cff`;
   - `NOTICE`;
   - `handover.md`;
   - `handover.zh-TW.md`;
   - release notes; and
   - external documentation.

Do not create an unrelated repository with the old repository name during the
transfer process.

---

## 11. Interim Licensing Status

The repository currently uses an interim all-rights-reserved notice.

Public availability does not grant permission to use, copy, modify,
redistribute, sublicense, or commercialize NMRpaint. Scientific, educational,
institutional, commercial, and private-sector use currently requires prior
written permission from the copyright holder.

Before transfer or public release, confirm:

1. who legally owns the original source code;
2. whether an employer, university, or research institute has an ownership
   claim;
3. whether all third-party code and resources may be publicly redistributed;
4. which email address will receive permission requests; and
5. whether `NOTICE` is consistent with the current interim `LICENSE`.

The interim notice is expected to be replaced by a formal license after the
related scientific publication and ownership review.

Do not describe NMRpaint as open-source software while the interim notice is in
effect.

---

## 12. Citation Metadata

Complete `CITATION.cff` before the first formal scientific release:

1. replace author placeholders;
2. add the verified ORCID;
3. add the repository URL;
4. add the web application URL;
5. set the version and release date;
6. add a DOI after archiving a release, when applicable; and
7. add the preferred paper citation after publication.

Do not invent an ORCID or DOI.

---

## 13. Handover Release

Recommended handover tag:

```text
v0.1.0-handover
```

Suggested release notes:

```markdown
## NMRpaint v0.1.0 Handover

Validated baseline for repository maintenance transfer.

- Python package structure validated
- Automated tests passing
- Voici browser application validated
- GitHub Pages deployment validated
- Browser download validated
- Interim licensing and citation files added
```

Create the release only after the current commit has passed deployment testing.

---

## 14. Recovery and Rollback

If a merged change breaks the application or deployment:

1. do not delete the repository;
2. do not delete Git history;
3. identify the last successful workflow run;
4. revert the breaking pull request or commit;
5. merge the revert after review; and
6. confirm that deployment succeeds again.

The handover release provides a known working reference point.

---

## 15. Handover Completion Checklist

- [ ] Placeholder values reviewed
- [ ] Copyright ownership reviewed
- [ ] Interim `LICENSE` and `NOTICE` are consistent
- [ ] New maintainer added as collaborator
- [ ] Documentation edit completed
- [ ] Small application edit completed
- [ ] Pull request workflow completed
- [ ] GitHub Actions result understood
- [ ] Voici deployment confirmed
- [ ] Handover release created
- [ ] Repository ownership transferred
- [ ] GitHub Pages rerun after transfer
- [ ] Repository and web URLs updated
- [ ] `CITATION.cff` reviewed
- [ ] Previous maintainer retained as collaborator
- [ ] Permission-request contact confirmed
