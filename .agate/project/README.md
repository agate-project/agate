# .agate/project/

This project's own extensions of Agate's tools. **`agate.py update` never touches this folder**: what you put here survives
base updates.

`.agate/core/lib/<tool>.py` loads `.agate/project/<tool>.py` if it exists and calls its optional hooks at fixed points
(Template Method). Today `mcp.py` supports it (see `.agate/core/guides/mcp-extend.md`):

```python
# .agate/project/mcp.py: everything optional. `mcp` (the base tool module) is available here.
class MyHarness:
    name = "myharness"
    def detect(self): ...                      # is this the harness running now?
    def config_path(self, root): ...           # where its config goes (relative to the project, or absolute)
    def render(self, servers): ...             # servers.json "servers" → that harness's format, as text (no secrets)
    def merge(self, existing, rendered): ...   # put it into the existing file without touching others' entries

HARNESSES = [MyHarness()]
def before_sync(servers): return servers       # adjust the list before generating
def after_sync(report): ...                    # something extra afterwards
def doctor_checks(name): return []             # extra lines for `agate.py mcp doctor <name>`
```

Safety: an extension is code that runs on this machine, sometimes from a git hook right after a pull. It runs only
once approved on each machine (`memory/local/approvals.json`). Your own changes are approved automatically; a
change by someone else waits until a person reviews it (`agate.py mcp extension review`, then `agate.py mcp extension approve`).

If an extension would help every project (for example, support for a new harness), suggest moving it into Agate.
