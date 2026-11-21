"""AppleScript (JXA) read backend: a drop-in subset of the ``things`` (things.py) API.

Why: on macOS 27 the SQLite database lives in a TCC-protected Group Container
that a server launched via Claude Desktop's ``disclaimer`` helper cannot open.
Talking to the Things app over Apple Events needs no filesystem access.

Not available (the Things scripting dictionary does not expose them, so no
amount of cleverness here can recover them without reading the database):
  * headings and checklist items
  * reminder times and repeating-template info
  * the URL-scheme auth token (supply it with THINGS_AUTH_TOKEN)

Bulk reads fetch one property across a whole collection per Apple Event, so a
list of a few hundred items costs ~0.5s.
"""
import json
import os
import subprocess
import time
from datetime import datetime, timedelta

_JXA = r"""
function run(argv) {
  const T = Application('Things3');
  const spec = JSON.parse(argv[0]);
  const pad = n => (n < 10 ? '0' : '') + n;
  const day = d => d ? d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) : null;
  const stamp = d => d ? day(d) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) : null;
  const tags = s => s ? s.split(',').map(x => x.trim()).filter(Boolean) : [];

  let c;
  switch (spec.kind) {
    case 'list':          c = T.lists.byName(spec.name).toDos; break;
    case 'project_todos': c = T.projects.byId(spec.id).toDos; break;
    case 'area_todos':    c = T.areas.byId(spec.id).toDos; break;
    case 'area_projects': c = T.areas.byId(spec.id).projects; break;
    case 'tag_todos':     c = T.tags.byName(spec.name).toDos; break;
    case 'all_todos':     c = T.toDos; break;
    case 'projects':      c = T.projects; break;
    case 'areas':
      return JSON.stringify(T.areas.id().map((id, i) => ({uuid: id, type: 'area',
        title: T.areas.name()[i], tags: tags(T.areas.tagNames()[i])})));
    case 'tags':
      return JSON.stringify(T.tags.id().map((id, i) => ({uuid: id, type: 'tag',
        title: T.tags.name()[i], shortcut: T.tags.keyboardShortcut()[i] || null})));
    default: throw new Error('unknown kind ' + spec.kind);
  }

  const ids = c.id(), names = c.name(), status = c.status(), notes = c.notes(),
        tg = c.tagNames(), due = c.dueDate(), act = c.activationDate(),
        cre = c.creationDate(), mod = c.modificationDate(),
        done = c.completionDate(), canc = c.cancellationDate(),
        proj = c.project.id(), area = c.area.id();
  const type = spec.kind === 'projects' || spec.kind === 'area_projects' ? 'project' : 'to-do';
  return JSON.stringify(ids.map((id, i) => ({
    uuid: id, type: type, title: names[i], status: status[i],
    notes: notes[i] || '', tags: tags(tg[i]),
    start_date: day(act[i]), deadline: day(due[i]),
    created: stamp(cre[i]), modified: stamp(mod[i]),
    stop_date: stamp(done[i] || canc[i]),
    project: proj[i] || null, area: area[i] || null,
  })));
}
"""

_JXA_GET = r"""
function run(argv) {
  const T = Application('Things3');
  const id = argv[0];
  const pad = n => (n < 10 ? '0' : '') + n;
  const day = d => d ? d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()) : null;
  const stamp = d => d ? day(d) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) : null;
  const tags = s => s ? s.split(',').map(x => x.trim()).filter(Boolean) : [];
  const idOf = o => { try { return o ? o.id() : null; } catch (e) { return null; } };
  for (const [coll, type] of [[T.toDos, 'to-do'], [T.projects, 'project'], [T.areas, 'area'], [T.tags, 'tag']]) {
    const o = coll.byId(id);
    try { o.name(); } catch (e) { continue; }
    if (type === 'area') return JSON.stringify({uuid: id, type, title: o.name(), tags: tags(o.tagNames())});
    if (type === 'tag')  return JSON.stringify({uuid: id, type, title: o.name()});
    return JSON.stringify({uuid: id, type, title: o.name(), status: o.status(), notes: o.notes() || '',
      tags: tags(o.tagNames()), start_date: day(o.activationDate()), deadline: day(o.dueDate()),
      created: stamp(o.creationDate()), modified: stamp(o.modificationDate()),
      stop_date: stamp(o.completionDate() || o.cancellationDate()),
      project: idOf(o.project()), area: idOf(o.area())});
  }
  return 'null';
}
"""


class ThingsReadError(RuntimeError):
    pass


def _osa(script, arg, timeout=60):
    try:
        r = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script, arg],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise ThingsReadError("Timed out talking to Things (is it running / Automation allowed?)") from e
    if r.returncode != 0:
        raise ThingsReadError(r.stderr.strip() or "osascript failed")
    return json.loads(r.stdout)


_QUERY_CACHE = {}
_QUERY_TTL = 5.0  # collapses repeated bulk fetches within one tool call


def _query(**spec):
    key = json.dumps(spec, sort_keys=True)
    hit = _QUERY_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < _QUERY_TTL:
        return [dict(i) for i in hit[1]]
    result = _osa(_JXA, key)
    _QUERY_CACHE[key] = (time.monotonic(), result)
    return [dict(i) for i in result]


def invalidate():
    """Drop cached reads. Called after every write so a read that follows sees it."""
    _QUERY_CACHE.clear()
    _CACHE.clear()


def _list(name, start):
    """Items of a built-in list. Things returns projects among a list's to-dos
    (e.g. a Someday project), so tag them by membership in the project set."""
    items = _query(kind="list", name=name)
    project_ids = {p["uuid"] for p in _query(kind="projects")}
    for i in items:
        i["start"] = start
        if i["uuid"] in project_ids:
            i["type"] = "project"
    return items


def _someday_ids():
    """UUIDs in the Someday list (projects and to-dos; callers intersect as needed)."""
    return {i["uuid"] for i in _query(kind="list", name="Someday")}


def _someday_project_ids():
    projects = {p["uuid"] for p in _query(kind="projects")}
    return _someday_ids() & projects


def _projects():
    someday = _someday_ids()
    items = _query(kind="projects")
    for i in items:
        i["start"] = "Someday" if i["uuid"] in someday else "Anytime"
    return items


# --- things.py-compatible surface -------------------------------------------

def inbox(include_items=False):
    return _list("Inbox", "Inbox")


def today(include_items=False):
    return _list("Today", "Anytime")


def upcoming(include_items=False):
    return _list("Upcoming", "Someday")  # scheduled items; the start list is not exposed


def anytime(include_items=False):
    """Anytime list, plus open to-dos inside Someday projects.

    Things hides those from its Anytime list, but things.py's anytime() returns
    them and the server relies on that to build get_someday (it filters them out
    of get_anytime/get_today itself)."""
    items = _list("Anytime", "Anytime")
    seen = {i["uuid"] for i in items}
    for proj in _someday_project_ids():
        for t in _query(kind="project_todos", id=proj):
            if t["status"] == "open" and t["uuid"] not in seen:
                t["start"] = "Anytime"
                items.append(t)
    return items


def someday(include_items=False):
    return _list("Someday", "Someday")


def logbook(include_items=False):
    return _list("Logbook", None)


def trash(include_items=False):
    return _list("Trash", None)


def areas(include_items=False, **_):
    return _query(kind="areas")


def tags(include_items=False, **_):
    return _query(kind="tags")


def projects(area=None, start=None, include_items=False, **_):
    items = _query(kind="area_projects", id=area) if area else _projects()
    if start:
        wanted = {i["uuid"]: i["start"] for i in _projects()}
        items = [i for i in items if wanted.get(i["uuid"]) == start]
    return items


# Per-process cache so formatters' repeated things.get() calls (parent project /
# area titles) cost one bulk fetch instead of one Apple Event round trip each.
_CACHE = {}
_CACHE_TTL = 30.0


def _prime():
    now = time.monotonic()
    for item in _projects() + _query(kind="areas") + _query(kind="tags"):
        _CACHE[item["uuid"]] = (now, item)


def get(uuid, **_):
    hit = _CACHE.get(uuid)
    if hit and time.monotonic() - hit[0] < _CACHE_TTL:
        return hit[1]
    _prime()
    hit = _CACHE.get(uuid)
    if hit:
        return hit[1]
    item = _osa(_JXA_GET, uuid)  # a to-do, or unknown -> None
    if item:
        _CACHE[uuid] = (time.monotonic(), item)
    return item


_UNSET = object()
_STATUS = {"incomplete": "open", "completed": "completed", "canceled": "canceled"}


def _date_matches(value, spec):
    """things.py-style date filter: 'past', 'future', 'YYYY-MM-DD', or an
    operator form such as '>=2024-01-01'. ``value`` may be a date or datetime string."""
    if not value:
        return False
    day = value[:10]
    today_ = datetime.now().strftime("%Y-%m-%d")
    if spec == "past":
        return day <= today_
    if spec == "future":
        return day > today_
    for op in (">=", "<=", ">", "<", "="):
        if spec.startswith(op):
            rhs = spec[len(op):]
            return {">=": day >= rhs, "<=": day <= rhs, ">": day > rhs, "<": day < rhs, "=": day == rhs}[op]
    return day == spec


def _created_since(item, period):
    unit = {"d": 1, "w": 7, "m": 30, "y": 365}[period[-1]]
    cutoff = datetime.now() - timedelta(days=int(period[:-1]) * unit)
    created = item.get("created")
    return bool(created) and datetime.fromisoformat(created.replace(" ", "T")) >= cutoff


def tasks(type=None, status=_UNSET, start=None, area=None, project=None, tag=None,
          start_date=None, stop_date=None, deadline=None, last=None, **_):
    """Python-side filtering over bulk reads (things.py does this in SQL).

    Mirrors things.py defaults: status defaults to incomplete, status=None means any.
    """
    if type == "heading":
        return []  # headings are not scriptable
    if status is _UNSET:
        status = "incomplete"
    wanted = _STATUS.get(status, status)
    if wanted in ("completed", "canceled"):
        pool = _list("Logbook", None)
    elif wanted is None:
        pool = _list("Logbook", None) + _query(kind="all_todos") + _projects()
    else:
        pool = _query(kind="all_todos") + _projects()
    items = [i for i in pool if wanted is None or i["status"] == wanted]
    if type:
        items = [i for i in items if i["type"] == type]
    if start:
        in_list = {i["uuid"] for i in _query(kind="list", name=start)}
        items = [i for i in items if i["uuid"] in in_list]
    if project:
        items = [i for i in items if i.get("project") == project]
    if area:
        items = [i for i in items if i.get("area") == area]
    if tag:
        items = [i for i in items if tag in i["tags"]]
    if start_date:
        items = [i for i in items if _date_matches(i.get("start_date"), start_date)]
    if stop_date:
        items = [i for i in items if _date_matches(i.get("stop_date"), stop_date)]
    if deadline:
        items = [i for i in items if _date_matches(i.get("deadline"), deadline)]
    if last:
        items = [i for i in items if _created_since(i, last)]
    return items


def todos(project=None, area=None, tag=None, heading=None, **kw):
    if heading:
        return []
    kw.pop("include_items", None)
    return tasks(type="to-do", project=project, area=area, tag=tag, **kw)


def search(query, **_):
    q = query.lower()
    return [i for i in tasks(status=None) if q in i["title"].lower() or q in (i["notes"] or "").lower()]


def last(period, **_):
    """Open items created within the last period (e.g. '3d'), like things.last()."""
    return tasks(last=period)


def token():
    """URL-scheme auth token. The database used to be the source; without it the
    user must provide one (Things > Settings > General > Things URLs > Manage)."""
    tok = (os.environ.get("THINGS_AUTH_TOKEN") or "").strip()
    if not tok or tok.startswith("${"):  # unset, or an unsubstituted manifest placeholder
        return None
    return tok
