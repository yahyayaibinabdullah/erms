"""Use one existing native Edge driver for the entire comparison."""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root))
from selenium.webdriver.edge import service
from tools import check_webui_browser as browser
path=root/'.runtime/selenium/msedgedriver/mac-arm64/157.0.4341.42/msedgedriver'
version=subprocess.check_output([str(path),'--version'],text=True).strip()
assert '157.0.4341.42' in version
BaseService=service.Service
class PinnedService(BaseService):
    def __init__(self, **kwargs):
        super().__init__(executable_path=str(path), **kwargs)
        self.path=str(path)
service.Service=PinnedService
original=browser.Acceptance.__init__
def observed(self,*args,**kwargs):
    original(self,*args,**kwargs)
    assert self.args.browser=='edge' and self.report['version']=='157.0.4341.42'
    self.report['driver_version']=version
    self.report['driver_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    self.report['driver_logging']='WARNING only; normal protocol commands are not logged'
    (self.args.output/'driver-selection.json').write_text(json.dumps({'browser_version':self.report['version'],'driver_version':version,'driver_sha256':self.report['driver_sha256'],'path':str(path.relative_to(root)),'logging':'WARNING'},indent=2)+'\n')
browser.Acceptance.__init__=observed
raise SystemExit(browser.main())
