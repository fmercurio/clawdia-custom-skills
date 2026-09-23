# Playwright Force Build boundary

Playwright is used only when the selected intent is an existing-app rebuild or a remote Git deployment. Plan mode performs only a static importability check; it does not launch a browser, read credentials or sessions, or make requests. Apply mode starts Playwright and prepares one local Chromium browser, context, and page without navigation before credential access or controller writes. The trigger reuses those exact resources, and every exit path closes them. Password authentication requires `--allow-login` and an exact `CAPROVER_CREDENTIAL_ORIGIN` binding. Both deployment forms require an explicit immutable full `--git-sha`; a rebuild whose configured source cannot produce that SHA is intentionally unsupported rather than weakly attributed.

`--git-sha` is accepted only in its original full lowercase 40-character format;
caller input is never normalized or rewritten.

The controller:

1. locally launches and prepares the browser, context, and page before credentials or writes, without navigating;
2. installs an origin-only route guard before navigation;
3. opens the login route and fills the password without logging it;
4. requires the login form to disappear;
5. opens the exact selected app route and requires the Deployment UI;
6. requires the immediately pre-trigger app definition to be idle and to contain
   the selected app's approved webhook token;
7. requires exactly one visible, enabled Force Build button;
8. arms exact request, response, and request-finished observers before one click,
   matching origin, webhook path, `POST`, `namespace=captain`, and the approved
   token;
9. requires the response and completion events to reference the exact request
   captured for that click, and requires it to finish within the deadline before
   its bounded body is parsed and HTTP/JSON status `100` is checked;
10. treats status `100` only as an acknowledgment and performs source-identity
   observation against a newer deployed version;
11. returns nonzero `reconcile_required` as acknowledged but unconfirmed even if
    the observed `gitHash` matches the explicit full `--git-sha`, because this
    webhook acknowledges before scheduling and exposes no synchronous option.

Any active build, missing token/UI, remaining login form, wrong route, disabled
Force Build, mismatched/rejected/timed-out response, click exception, or
cross-origin request fails. A possibly dispatched click is inconclusive and is
never retried or routed to a fallback. There is no Save & Restart fallback and no
silent click recovery. A headers-only response cannot outlive the configured
deadline. No Force Build path prints `deployment_evidence_verified`. HTTPS and
WebSocket controls are outside this deployment operation.

The browser trigger is not CapRover "method 3" remote-Git deployment terminology; it is explicit dashboard automation for Force Build after any separately verified Git configuration update.
