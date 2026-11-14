from pathlib import Path
import frontend.webui.aggregation_actions as actions
exec(compile(Path('.runtime/governed-move-details-fix/before-aggregation-actions.py').read_text(), actions.__file__, 'exec'), actions.__dict__)
