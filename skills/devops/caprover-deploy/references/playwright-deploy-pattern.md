# Playwright Force Build boundary

Playwright is used only when the selected intent is an existing-app rebuild or a remote Git deployment. Availability is checked before credential access or writes. Password authentication requires `--allow-login` and an exact `CAPROVER_CREDENTIAL_ORIGIN` binding.

The controller:

1. installs an origin-only route guard before navigation;
2. opens the login route and fills the password without logging it;
3. requires the login form to disappear;
4. opens the exact selected app route and requires the Deployment UI;
5. requires exactly one visible, enabled Force Build button;
6. clicks it once, then verifies through API baseline/evidence polling.

Any missing UI, remaining login form, wrong route, disabled Force Build, click exception, or cross-origin request fails. There is no Save & Restart fallback and no silent click recovery. HTTPS and WebSocket controls are outside this deployment operation.

The browser trigger is not CapRover "method 3" remote-Git deployment terminology; it is explicit dashboard automation for Force Build after any separately verified Git configuration update.
