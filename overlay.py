#!/usr/bin/env python3
"""Generate browser compatibility API data to be requested from MDN pages."""

import copy
import json
import pathlib
import subprocess
import sys
import tempfile

import frontmatter

from lib import bcd
from lib.support import Support

root_path = pathlib.Path(__file__).parent
surfly_path = root_path / "features"
data_branch = "data"
output_dir_name = "scd"
ANSI_CLEAR_LINE = "\x1b[2K\r"
edit_url_prefix = (
    "https://app.pagescms.org/qguv/surfly-compat-data/main/content/features/edit/"
)

supported_browser_ids = [
    "chrome",
    "chrome_android",
    "firefox",
    "firefox_android",
    "safari",
    "safari_ios",
]


def overlay(bcd_root, supported_browser_ids):
    for path in surfly_path.glob("**/*.html"):
        fm = frontmatter.load(path)
        feature_id = fm["id"]
        surfly_version_added = fm.get("version_added")
        support = Support[fm["support"].upper()]
        limitations = fm.get("limitations", "")
        icf_support_raw = fm.get("icf_support", "")
        icf_limitations = fm.get("icf_limitations", "")
        extra_note = str(fm)

        # handle empty support
        icf_support = Support[icf_support_raw.upper()] if icf_support_raw else support

        try:
            feature = bcd.get_feature(bcd_root, feature_id)
        except KeyError as e:
            raise Exception(
                f"feature {feature_id} was removed from browser-compat-data!"
            ) from e

        feature["mdn_url"] = get_edit_url(path)

        native_browser_supports = feature["support"]
        feature["support"] = {}

        for browser_id in supported_browser_ids:
            try:
                native_support_entries = native_browser_supports[browser_id]
            except KeyError:
                continue

            # carry over original support data from native browser
            feature["support"][browser_id] = native_support_entries

            # we only care about the latest support entry
            latest_native_support_entry = get_latest_support_entry(
                native_support_entries
            )

            # create "Surfly browser" column: start with a copy of the native browser support data
            surfly_support_entry = create_surfly_support_entry(
                latest_native_support_entry,
                surfly_version_added,
                support,
                limitations,
                icf_support,
                icf_limitations,
                extra_note,
            )
            feature["support"][f"surfly_{browser_id}"] = surfly_support_entry


def get_edit_url(path):
    return edit_url_prefix + str(path.relative_to(root_path)).replace("/", "%2F")


def capitalize(s):
    """capitalize first word without lowercasing subsequent words"""
    words = s.split(" ", maxsplit=1)
    words[0] = words[0].title()
    return " ".join(words)


def get_latest_support_entry(support_entries):
    return (
        support_entries[0]
        if isinstance(support_entries, list) and support_entries
        else support_entries
    )


def is_supported(support_entry):
    return support_entry.get("version_added") and not support_entry.get(
        "version_removed"
    )


def create_surfly_support_entry(
    latest_native_support_entry,
    surfly_version_added,
    support,
    limitations,
    icf_support,
    icf_limitations,
    extra_note,
):
    if not is_supported(latest_native_support_entry):
        return dict(version_added=False)

    if support == Support.UNKNOWN:
        surfly_support_entry = dict(version_added=None)

    elif support in (Support.TODO, Support.NEVER):
        surfly_support_entry = dict(version_added=False)

    else:
        surfly_support_entry = copy.deepcopy(latest_native_support_entry)

        if (
            limitations.strip()
            or icf_limitations.strip()
            or icf_support not in (Support.SUPPORTED, Support.EXPECTED)
        ):
            surfly_support_entry["partial_implementation"] = True

        surfly_support_entry["version_added"] = surfly_version_added or True

    for n in create_support_notes(
        support, limitations, icf_support, icf_limitations, extra_note
    ):
        add_note(surfly_support_entry, n)

    return surfly_support_entry


def create_support_notes(
    support, limitations, icf_support, icf_limitations, extra_note
):
    if extra_note.strip():
        yield extra_note

    icf_notes = []
    if support != icf_support:
        if icf_support == Support.UNKNOWN:
            icf_notes.append("unknown support.")
        elif icf_support == Support.SUPPORTED:
            icf_notes.append("supported.")
        elif icf_support == Support.EXPECTED:
            icf_notes.append("expected to work.")
        elif icf_support == Support.TODO:
            icf_notes.append("not yet supported.")
        elif icf_support == Support.NEVER:
            icf_notes.append("cannot support due to a browser limitation.")
    if icf_limitations.strip():
        icf_notes.append(icf_limitations)
    if icf_notes:
        icf_notes.insert(0, "<strong>Controlling another user's tab:</strong>")
        yield " ".join(icf_notes)

    notes = []
    if support == Support.NEVER:
        notes.append("cannot support due to a browser limitation.")
    elif support == Support.EXPECTED:
        notes.append("expected to work.")
    elif support == Support.UNKNOWN:
        notes.append("unknown Surfly support.")
    elif icf_notes and support == Support.SUPPORTED:
        notes.append("full Surfly support.")
    if limitations.strip():
        notes.append(limitations)
    if notes:
        if icf_notes:
            notes.insert(0, "<strong>Tab owner in control:</strong>")
            yield " ".join(notes)
        else:
            yield capitalize(" ".join(notes))


def add_note(support_entry, new_note):
    try:
        notes = support_entry["notes"]
    except KeyError:
        support_entry["notes"] = new_note
        return

    if isinstance(notes, str):
        support_entry["notes"] = [new_note, notes]
        return

    notes.insert(0, new_note)


def overlay_browsers(upstream_browsers, supported_browser_ids):
    for browser_id in supported_browser_ids:
        upstream_browser = upstream_browsers[browser_id]
        if browser_id == "chrome":
            upstream_browser["name"] = "Chrome/Edge"
        yield (browser_id, upstream_browser)

        surfly_browser = upstream_browser.copy()
        surfly_browser["name"] = f'Surfly on {upstream_browser["name"]}'
        yield (f"surfly_{browser_id}", surfly_browser)


def export(output_path, feature_data, browsers, feature_id=None):
    for k, subfeature_data in feature_data.items():
        if k == "__compat":
            out = dict(
                browsers=browsers,
                query=feature_id,
                data=feature_data,
            )
            feature_path = output_path / f"{feature_id}.json"
            print(f"{ANSI_CLEAR_LINE}{feature_path.name}", end="\r", file=sys.stderr)
            with (output_path / f"{feature_id}.json").open("w") as f:
                json.dump(out, f, separators=",:")

        elif isinstance(subfeature_data, dict):
            export(
                output_path,
                subfeature_data,
                browsers,
                feature_id=k if feature_id is None else f"{feature_id}.{k}",
            )


def git_something_staged(worktree_path):
    res = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=worktree_path)
    return res.returncode == 1


def update(data_worktree_path):
    output_path = pathlib.Path(data_worktree_path) / output_dir_name
    output_path.mkdir()

    print("Downloading latest bcd data...", file=sys.stderr)
    bcd_root = bcd.download()

    print("Creating overlay data...", file=sys.stderr)
    all_browsers = bcd_root.pop("browsers")
    browsers = dict(overlay_browsers(all_browsers, supported_browser_ids))
    overlay(bcd_root, supported_browser_ids)
    export(output_path, bcd_root, browsers)
    print(f"{ANSI_CLEAR_LINE}Done!", file=sys.stderr)

    print("Checking for changes...", file=sys.stderr)
    subprocess.check_call(["git", "add", output_dir_name], cwd=data_worktree_path)

    if git_something_staged(data_worktree_path):
        print("Committing changes to the `data` branch... ", end="", file=sys.stderr)
        subprocess.check_call(
            ["git", "commit", "-m", "regenerate overlay data"],
            cwd=data_worktree_path,
        )

        print("\nDone! You can now push the `data` branch.", file=sys.stderr)
    else:
        print("No changes found; data was already up-to-date.", file=sys.stderr)


with tempfile.TemporaryDirectory() as data_worktree_path:
    try:
        subprocess.check_call(
            ["git", "worktree", "add", "--no-checkout", data_worktree_path, data_branch],
            cwd=root_path,
        )
    except subprocess.CalledProcessError:
        sys.exit(1)

    try:
        update(data_worktree_path)
    except KeyboardInterrupt:
        print("\n", file=sys.stderr)
        pass
    finally:
        subprocess.check_call(
            ["git", "worktree", "remove", "--force", str(data_worktree_path)],
            cwd=root_path,
        )
