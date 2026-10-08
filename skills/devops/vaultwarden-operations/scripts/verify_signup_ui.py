#!/usr/bin/env python3
"""Fresh unauthenticated browser check; never attach a human browser/profile."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

NOTICE = 'Cadastro encerrado. Entre com sua conta existente.'
ROOT = Path(__file__).resolve().parents[1]


def verify(page, synthetic, origin, stylesheet):
    results = []
    for route in ('signup', 'register', 'login'):
        if synthetic:
            if route == 'login':
                html = '<h1>Log in</h1><form><input type="email"><button>Log in</button></form>'
            else:
                html = '<h1>Create account</h1><auth-registration-start><form><input type="email"><button>Create</button></form><a href="#/login">Log in</a></auth-registration-start>'
            page.set_content(html)
            if route != 'login' and page.locator('form:visible').count() != 1:
                raise RuntimeError('synthetic_baseline_missing')
            page.add_style_tag(content=stylesheet)
        else:
            page.goto(origin+'/#/'+route, wait_until='networkidle', timeout=30000)
        if route == 'login':
            passed = page.locator('form:visible').count() == 1 and page.locator('input:visible').count() > 0
            results.append({'route': route, 'login_preserved': passed})
        else:
            host = page.locator('auth-registration-start')
            closure = host.count() == 1 and NOTICE in host.evaluate('(x)=>getComputedStyle(x,"::before").content')
            link = page.locator('a[href="#/login"]:visible')
            passed = (page.locator('form:visible').count() == 0
                      and page.locator('input:visible').count() == 0 and closure and link.count() == 1)
            navigates = False
            if not synthetic and passed:
                link.click()
                page.wait_for_url('**/#/login', timeout=10000)
                navigates = page.locator('form:visible').count() == 1
                passed = passed and navigates
            results.append({'route': route, 'signup_screen_closed': passed,
                            'login_link_works': navigates if not synthetic else None})
        if not passed:
            raise RuntimeError('signup_ui_verification_failed')
    return {'status': 'verified', 'synthetic_fixture_only': synthetic, 'routes': results,
            'authenticated_human_acceptance': False, 'server_policy_assessed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--synthetic', action='store_true')
    group.add_argument('--live', action='store_true')
    args = parser.parse_args()
    try:
        # Configuration through bounded stdin, never URL/credential arguments.
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        cfg = json.loads(raw or b'{}')
        if not isinstance(cfg, dict) or set(cfg)-{'server_origin','browser_executable'}:
            raise ValueError()
        origin = cfg.get('server_origin', '')
        executable = cfg.get('browser_executable')
        if args.live:
            parsed = urlsplit(origin)
            if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                    or parsed.password or parsed.path or parsed.query or parsed.fragment):
                raise ValueError()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=executable)
            try:
                page = browser.new_page()
                result = verify(page, args.synthetic, origin,
                                (ROOT/'templates/user.vaultwarden.scss.hbs').read_text())
            finally:
                browser.close()
        print(json.dumps(result, sort_keys=True))
        return 0
    except BaseException:
        print(json.dumps({'status':'failed','gate':'signup_ui_verification_failed',
                          'authenticated_human_acceptance':False}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
