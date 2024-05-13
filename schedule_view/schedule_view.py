import argparse
from pathlib import Path

import kadi.commands as kc
import numpy as np
from astropy.table import Table, vstack
from jinja2 import Template
from kadi import paths
from mica.utils import load_name_to_mp_dir

TEMPLATE = Path(__file__).parent / "index_template.html"


def get_options():
    parser = argparse.ArgumentParser(description="View schedule")
    parser.add_argument("--start", type=str, help="Start time")
    parser.add_argument("--outdir", type=str, help="Output directory", default=".")
    return parser


def get_sched_files():
    """
    Get a list of the files with SOT MP schedules.

    This tool is only useful for viewing schedules in the RLTT era, so
    there's a small optimization that this only fetches files from cycle 20
    on. This will only succeed on HEAD systems with access to /proj/web-icxc.

    Returns
    -------
    files : list
        A list of Path objects representing the schedule files.

    """
    files = []
    top_level = "/proj/web-icxc/htdocs/mp/html/"
    for glob in ["schedules_ao2?.html", "schedules.html"]:
        sched_files = list(Path(top_level).glob(glob))
        sched_files.sort()
        files.extend(sched_files)
    return files


def get_mp_scheds(files):
    """
    Get an astropy table of the entries from the SOT MP schedule tables.

    Parameters
    ----------
    files : list
        A list of Path objects representing the schedule files.

    Returns
    -------
    out : astropy.table.Table
        A table with the columns "Week", "Version", and "Comment" with the
        entries from the SOT MP schedule tables.
    """
    dat = []
    for sched_file in files:
        tab = Table.read(sched_file, header_start=0, data_start=1)
        # If all the comments are empty or masked, replace with emtpy string
        if np.all(tab["Comment"].mask):
            tab.remove_column("Comment")
            tab["Comment"] = ""
        week_mask = tab["Week"].mask
        week_name = None
        for row, ismasked in zip(tab, week_mask):
            # if row['Week'] is masked, fill it in with the previous value
            if ismasked and week_name is not None:
                row["Week"] = week_name
            if row["Week"] is not None:
                week_name = row["Week"]

        # Just keep the comments and the week, and flip sort so it is ascending
        dat.append(tab["Week", "Version", "Comment"][::-1])

    out = vstack(dat)
    return out


def get_mp_comment(week, mp_scheds):
    """
    Get any SOT MP comments on week.

    Parameters
    ----------
    week : str
        The week string, e.g. "FEB2324A"
    mp_scheds : astropy.table.Table
        The table of SOT MP schedules from get_mp_scheds.

    Returns
    -------
    comment : str or None
    """
    mp_week = week[0:7]
    mp_match = (mp_scheds["Week"] == mp_week) & (mp_scheds["Version"] == week[7])
    if np.any(mp_match):
        return mp_scheds[mp_match]["Comment"][0]


def get_starcheck_url(week):
    """
    Construct URL for Flight starcheck output for week.

    Parameters
    ----------
    week : str
        The week string, e.g. "FEB2324A"

    Returns
    -------
    url : str

    """
    week_str = load_name_to_mp_dir(week)
    return f"https://icxc.harvard.edu/mp/mplogs{week_str}starcheck.html"


def get_page_entries(start_time):
    """
    Get the entries for the schedule view page.

    Parameters
    ----------
    start_time : CxoTime or compatible str
        The start time for the list of cmds and events to be considered.

    Returns
    -------
    entries : list
        A list of dictionaries with the keys including "date", "products", "mp_comment".
    """

    # Get kadi dynamic commands from start_time
    cmds = kc.get_cmds(start=start_time)
    ok = (
        (cmds["type"] == "LOAD_EVENT")
        & (cmds["tlmsid"] == "None")
        & (cmds["source"] != "CMD_EVT")
    )
    cmds = cmds[ok]
    cmds.fetch_params()

    # Get a sorted list of the approved/run loads
    _, idx = np.unique(cmds["source"], return_index=True)
    run_loads = list(cmds["source"][np.sort(idx)])

    # Get the command events from the sheet
    path_flight = paths.CMD_EVENTS_PATH()
    events_flight = Table.read(path_flight)
    events_flight.rename_column("Date", "date")
    ok = events_flight["date"] > start_time
    events_flight = events_flight[ok]

    # Get SOT MP comments
    sched_files = get_sched_files()
    mp_dat = get_mp_scheds(sched_files)

    # For the set of approved loads, add a dictionary for each to a list of entries for the
    # output table. Check if there are command events / nonload commands between rltt and
    # schedule_stop to get a quick idea about if the schedule was interrupted, and if so
    # update a key in the dictionary with that information.
    entries = []
    for week in run_loads:
        entry = {"products": week}
        mp_comment = get_mp_comment(week, mp_dat)
        if mp_comment is not None:
            entry["mp_comment"] = mp_comment
        rltt_match = (cmds["source"] == week) & (
            cmds["params"] == {"event_type": "RUNNING_LOAD_TERMINATION_TIME"}
        )
        if any(rltt_match):
            rltt = cmds["date"][rltt_match][0]
            entry["rltt"] = rltt
            entry["date"] = rltt
        else:
            continue
        ss_match = (cmds["source"] == week) & (
            cmds["params"] == {"event_type": "SCHEDULED_STOP_TIME"}
        )
        if any(ss_match):
            ss = cmds["date"][ss_match][0]
            entry["sched_stop"] = ss
        if "rltt" in entry and "sched_stop" in entry:
            other_cmds = cmds[(cmds["date"] > rltt) & (cmds["date"] < ss)]
            other_events = events_flight[
                (events_flight["date"] > rltt) & (events_flight["date"] < ss)
            ]
            if len(other_cmds) == 0 and len(other_events) == 0:
                entry["status"] = "Ran nominally"
            else:
                entry["status"] = ""
                entry["ss_color"] = "grey"
        entries.append(entry)

    # For each entry from the command events sheet, if that entry is a Load not run
    # or Observing not run entry, use that to update the entry already in entries
    # for that week/schedule.  If for any reason there is a Load or Observing not
    # run without a matching cmd, put that in the list of entries too.
    for entry in events_flight:
        if entry["Event"] in ["Load not run", "Observing not run"]:
            # Is there already an entry for this week? if so, update in place
            week_entry = {}
            has_entry = False
            for e in entries:
                if (e["products"] == entry["Params"]) and e.get("rltt") is not None:
                    week_entry = e
                    has_entry = True
                    break
            week_entry.update(
                {
                    "date": entry["date"],
                    "products": entry["Params"],
                    "Event": entry["Event"],
                    "Comment": entry["Comment"],
                }
            )
            mp_comment = get_mp_comment(entry["Params"], mp_dat)
            if mp_comment is not None:
                week_entry["mp_comment"] = mp_comment
            if not has_entry:
                entries.append(week_entry)

    # For the remaining entries, do a little bit of munging to add space to the Params
    # so they will wrap better on the HTML page, and save them to the entries list too.
    events_flight_list = []
    params_mask = events_flight["Params"].mask
    for row, pmask in zip(events_flight, params_mask):
        if row["Event"] in ["Load not run", "Observing not run"]:
            continue
        entry = dict(zip(events_flight.colnames, row))
        # Update params to add whitespace that can be split
        if "Params" in entry and not pmask:
            entry["Params"] = entry["Params"].replace(",", ", ")

        entry["source"] = "cmd_evt"
        events_flight_list.append(entry)
    entries.extend(events_flight_list)

    # Update the entries with defined weeks to have links to starcheck.
    for entry in entries:
        if "products" in entry:
            entry["starcheck_url"] = get_starcheck_url(entry["products"])

    # Sort by date
    entries.sort(key=lambda x: x["date"])

    return entries


def main(sys_argv=None):
    opt = get_options().parse_args(sys_argv)
    start_time = opt.start or "2020:110"

    entries = get_page_entries(start_time)

    # Make HTML
    template = Template(open(TEMPLATE).read())
    html = template.render(
        entries=entries[::-1],
    )

    Path(opt.outdir).mkdir(exist_ok=True, parents=True)
    outfile = Path(opt.outdir) / "index.html"

    with open(outfile, "w") as fh:
        fh.write(html)


if __name__ == "__main__":
    main()
