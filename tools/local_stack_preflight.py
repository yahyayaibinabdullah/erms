"""Reject occupied/mismatched local service ports before starting workers."""
import argparse
import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request


def expected_service(url, kind):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        request = urllib.request.Request(url.rstrip('/') + ('/health' if kind == 'api' else '/'),
                                         headers={'Accept': 'application/json' if kind == 'api' else 'text/html'})
        with opener.open(request, timeout=2) as response:
            body = response.read(1024 * 1024).decode('utf-8', errors='replace')
            if response.status != 200:
                return False
            if kind == 'api':
                data = json.loads(body)
                return isinstance(data, dict) and data.get('status') == 'ok' and 'notifications' in data and 'messaging_realtime' in data
            return '_nicegui/' in body and 'wathiq' in body.lower()
    except (OSError, ValueError):
        return False


def check(url, kind, bind_host, bind_port):
    if expected_service(url, kind):
        return None
    target = urllib.parse.urlsplit(url)
    port = target.port or (443 if target.scheme == 'https' else 80)
    label = 'API' if kind == 'api' else 'Web UI'
    variables = 'API_PORT and WEBUI_API_URL' if kind == 'api' else 'WEBUI_PORT and ERMS_LOCAL_UI_URL'
    if target.hostname not in {'127.0.0.1', 'localhost', '::1'}:
        return f'{label} at the configured remote URL is unavailable or is not Wathiq; refusing to start a local replacement.'
    if port != bind_port:
        return f'{label} URL port {port} differs from configured bind port {bind_port}; set {variables} consistently.'
    try:
        with socket.create_connection((target.hostname, port), timeout=1):
            return f'{label} port {port} is occupied by a service that is not a healthy Wathiq {label}. Stop its owner yourself or choose a free port using {variables}.'
    except ConnectionRefusedError:
        pass
    except OSError as error:
        return f'{label} port {port} could not be checked ({type(error).__name__}); inspect the local network/bind configuration.'
    # macOS can allow a wildcard bind beside a loopback-specific listener;
    # therefore the connect check above must precede this bind check.
    family = socket.AF_INET6 if ':' in bind_host else socket.AF_INET
    try:
        with socket.socket(family) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((bind_host, bind_port))
    except OSError:
        return f'{label} bind port {bind_port} is unavailable; choose a free port using {variables}.'
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', required=True)
    parser.add_argument('--api-host', required=True)
    parser.add_argument('--api-port', type=int, required=True)
    parser.add_argument('--ui-url', required=True)
    parser.add_argument('--ui-host', required=True)
    parser.add_argument('--ui-port', type=int, required=True)
    args = parser.parse_args()
    errors = [check(args.api_url, 'api', args.api_host, args.api_port),
              check(args.ui_url, 'webui', args.ui_host, args.ui_port)]
    for error in errors:
        if error:
            print('Local stack preflight: ' + error, file=sys.stderr)
    return 1 if any(errors) else 0


if __name__ == '__main__':
    sys.exit(main())
