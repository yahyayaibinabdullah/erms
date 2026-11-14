#!/Users/yahyayai/Offline-Documents/code/erms/.runtime/webui-browser-venv/bin/python
import sys,os,json,hashlib
from pathlib import Path
sys.path.insert(0,os.getcwd())
from tools import check_webui_browser as checker

def transitions(self):
    source=Path(__file__).read_bytes()
    (self.args.output/'transition-driver.py').write_bytes(source)
    self.report['supplemental_driver_sha256']=hashlib.sha256(source).hexdigest()
    self.driver.set_window_size(1440,1100)
    self.driver.get(self.args.url+'/')
    self.login();self.settings()
    for i in range(12):
        with self.check('root reload to custody transition '+str(i+1)):
            self.reload()
            self.field(self.t('settings.field.review_warning_window_days.label'))
            self.tab('general')
            self.drawer('governance_custody')
            self.click(self.t('settings.custody.open'))
            self.wait.until(lambda _:checker.plain(self.one('[role=tab][aria-selected=true]').text)==self.t('settings.category.disposition'))
            self.tab('general')
    self.errors()
    self.report['complete']=True
checker.Acceptance.run=transitions
sys.argv.pop(1)
raise SystemExit(checker.main())
