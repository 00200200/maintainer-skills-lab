# README assets

`hero.svg` is the editable vector banner. `workflow.gif` illustrates the source-to-
provider generation process; it is not a recording of a client or benchmark.
The same information is available as text and paths in the main README.

To regenerate the animation, install Pillow in a development environment and run:

```sh
python3 tools/render_readme.py
```

The script uses Arial on macOS or DejaVu Sans on Linux when available. Otherwise
pass `--font /path/regular.ttf --bold-font /path/bold.ttf`. Pillow and these fonts
are optional asset-authoring tools, not dependencies of the library or installer.

## GitHub statistics

A maintainer with access to repository traffic can use their existing GitHub CLI
login to refresh `community.json` and `community.svg`:

```sh
python3 tools/repo_stats.py
```

The script reads repository counts, all pages of current stargazers, and GitHub's
14-day views endpoint. It keeps aggregate counts and dates only, without account
names, visitor identities, API keys, or tokens. It never sends a credential to a
badge or chart service. Views and unique visitors are totals for the returned
window, not lifetime counts. GitHub analytics can lag behind current activity.

The chart groups **current stargazers** by the date they starred the project.
Removed stars are unavailable from this endpoint, so this is not a reconstruction
of historical net star totals. A repository with no stars shows no invented
points; a single star date appears as one dot.

A failed API request or inconsistent star count leaves the previous snapshot
untouched. Refresh alongside substantive repository changes; don't create
statistics-only or timestamp-only activity commits. The main README links the
underlying dated data, and public badges may have their own cache delay.

Primary references:
[Repository traffic](https://docs.github.com/en/rest/metrics/traffic#get-page-views) ·
[Stargazers](https://docs.github.com/en/rest/activity/starring#list-stargazers) ·
[Repository metadata](https://docs.github.com/en/rest/repos/repos#get-a-repository).
