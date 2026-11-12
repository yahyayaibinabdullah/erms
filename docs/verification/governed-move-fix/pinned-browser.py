"""Use existing fixed browser drivers; do not install or update browsers/drivers."""
import hashlib,json,subprocess,sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root))
name=sys.argv[sys.argv.index('--browser')+1]
if name=='edge':
 from selenium.webdriver.edge import service
 path=root/'.runtime/selenium/msedgedriver/mac-arm64/157.0.4341.42/msedgedgedriver'
 path=path.with_name('msedgedriver')
else:
 assert name=='chrome'
 from selenium.webdriver.chrome import service
 path=root/'.runtime/selenium/chromedriver/mac-arm64/157.0.8103.50/chromedriver'
version=subprocess.check_output([str(path),'--version'],text=True).strip()
BaseService=service.Service
class PinnedService(BaseService):
 def __init__(self,**kwargs):
  super().__init__(executable_path=str(path),**kwargs)
  self.path=str(path)
service.Service=PinnedService
from tools import check_webui_browser as browser
original=browser.Acceptance.__init__
expected=json.loads((root/'.runtime/governed-move-fix/installed-browsers.json').read_text())[name]['version']
def observed(self,*args,**kwargs):
 original(self,*args,**kwargs)
 assert self.report['version']==expected,(self.report['version'],expected)
 self.report.update(driver_version=version,driver_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
 (self.args.output/'driver-selection.json').write_text(json.dumps({'browser_version':self.report['version'],'driver_version':version,'driver_sha256':self.report['driver_sha256'],'path':str(path.relative_to(root)),'logging':'WARNING for Edge; default Chrome; no verbose command logging'},indent=2)+'\n')
browser.Acceptance.__init__=observed
# Retain native hit-test diagnostics if the language selector click is intercepted.
from selenium.common.exceptions import ElementClickInterceptedException
language_change = browser.Acceptance.language_change
def observed_language_change(self, language):
 try:
  return language_change(self, language)
 except ElementClickInterceptedException:
  field = self.field(self.t('preferences.field.language'))
  details = self.driver.execute_script("const r=arguments[0].getBoundingClientRect(); return {input:arguments[0].outerHTML,rect:r.toJSON(),hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.outerHTML,control:arguments[0].closest('.q-field')?.outerHTML}",field)
  (self.args.output/'language-click-diagnostic.json').write_text(json.dumps(details,indent=2)+'\n')
  self.driver.save_screenshot(str(self.args.output/'language-click-intercepted.png'))
  raise
browser.Acceptance.language_change = observed_language_change
raise SystemExit(browser.main())
