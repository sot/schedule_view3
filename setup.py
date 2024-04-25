# Licensed under a 3-clause BSD style license - see LICENSE
from setuptools import setup

entry_points = {
    "console_scripts": [
        "schedule_view_update_page=schedule_view.schedule_view:main",
    ]
}

setup(
    name="schedule_view",
    author="Jean Connelly",
    description="Show schedules and events in a web page",
    author_email="jconnelly@cfa.harvard.edu",
    url="https://sot.github.io/schedule_view3",
    use_scm_version=True,
    setup_requires=["setuptools_scm", "setuptools_scm_git_archive"],
    zip_safe=False,
    license=(
        "New BSD/3-clause BSD License\nCopyright (c) 2023"
        " Smithsonian Astrophysical Observatory\nAll rights reserved."
    ),
    entry_points=entry_points,
    packages=["schedule_view"],
    package_data={
        "schedule_view": [
            "index_template.html",
            "task_schedule.cfg",
        ]
    },
)
