"""Run the unchanged timing journey and record slow WebDriver commands."""
import json,sys,time
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root))
from tools import check_webui_browser as browser
from selenium.webdriver.remote.command import Command
create=browser.create_driver

def observed_create(name,output):
    driver=create(name,output);execute=driver.execute;path=Path(output)/'webdriver-command-timings.jsonl'
    def observed(command,params=None):
        started=time.monotonic()
        try:
            result=execute(command,params)
            if command==Command.W3C_EXECUTE_SCRIPT_ASYNC:
                observation=execute(Command.W3C_EXECUTE_SCRIPT,{'script':"return {nodes:document.querySelectorAll('*').length,styles:document.querySelectorAll('style,link[rel=stylesheet]').length,scripts:document.scripts.length,js_heap_bytes:performance.memory?.usedJSHeapSize ?? null}",'args':[]})['value']
                with (Path(output)/'browser-memory-observations.jsonl').open('a') as file:
                    file.write(json.dumps({'monotonic':time.monotonic(),**observation})+'\n')
            return result
        finally:
            elapsed=(time.monotonic()-started)*1000
            if elapsed>=50:
                with path.open('a') as file:file.write(json.dumps({'command':command,'monotonic':started,'milliseconds':elapsed,'parameters_recorded':False})+'\n')
    driver.execute=observed
    return driver
browser.create_driver=observed_create
raise SystemExit(browser.main())
