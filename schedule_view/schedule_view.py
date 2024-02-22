from pathlib import Path

import kadi.commands as kc
import numpy as np
from astropy.table import Table, vstack
from jinja2 import Template
from kadi import paths

TEMPLATE = Path(__file__).parent / "index_template.html"


def get_options():
    import argparse

    parser = argparse.ArgumentParser(description="View schedule")
    parser.add_argument("--start", type=str, help="Start time")
    parser.add_argument("--out-dir", type=str, help="Output directory", default=".")
    return parser


def get_sched_files():
    files = []
    top_level = "/proj/web-icxc/htdocs/mp/html/"
    for glob in ["schedules_ao2?.html", "schedules.html"]:
        sched_files = list(Path(top_level).glob(glob))
        sched_files.sort()
        files.extend(sched_files)
    return files


def get_mp_scheds(files):
    dat = []
    for sched_file in files:
        tab = Table.read(sched_file, header_start=0, data_start=1)

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
    mp_week = week[0:7]
    mp_match = (mp_scheds["Week"] == mp_week) & (mp_scheds["Version"] == week[7])
    if np.any(mp_match):
        return mp_scheds[mp_match]["Comment"][0]


def get_starcheck_url(week):
    from mica.utils import load_name_to_mp_dir

    week_str = load_name_to_mp_dir(week)
    return f"https://icxc.harvard.edu/mp/mplogs{week_str}starcheck.html"


def main(sys_argv=None):
    opt = get_options().parse_args(sys_argv)
    start_time = opt.start or "2020:110"

    cmds = kc.commands.get_cmds(start=start_time)
    ok = (
        (cmds["type"] == "LOAD_EVENT")
        & (cmds["tlmsid"] == "None")
        & (cmds["source"] != "CMD_EVT")
    )
    cmds = cmds[ok]
    cmds.fetch_params()

    _, idx = np.unique(cmds["source"], return_index=True)
    run_loads = list(cmds["source"][np.sort(idx)])

    path_flight = paths.CMD_EVENTS_PATH()
    events_flight = Table.read(path_flight)
    events_flight.rename_column("Date", "date")
    ok = events_flight["date"] > start_time
    events_flight = events_flight[ok]

    sched_files = get_sched_files()
    mp_dat = get_mp_scheds(sched_files)

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

    for entry in entries:
        if "products" in entry:
            entry["starcheck_url"] = get_starcheck_url(entry["products"])

    entries.sort(key=lambda x: x["date"])

    template = Template(open(TEMPLATE).read())
    html = template.render(
        entries=entries[::-1],
    )

    outfile = Path(opt.out_dir) / "index.html"
    with open(outfile, "w") as fh:
        fh.write(html)


if __name__ == "__main__":
    main()
