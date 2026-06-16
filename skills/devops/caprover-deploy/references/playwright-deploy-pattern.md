# Playwright Deploy Pattern for CapRover

When the CapRover CLI and REST API can't trigger a Git-based build, use Playwright headless browser automation to interact with the dashboard.

## Prerequisites

```bash
pip install playwright
playwright install chromium
```

## Pattern

### 1. Login

```python
page.goto(f"{caprover_url}/#/login")
page.wait_for_timeout(2000)
page.locator('input[type="password"]').fill(password)
page.locator('button:has-text("Login")').click()
page.wait_for_timeout(3000)
```

### 2. Navigate to app

```python
page.goto(f"{caprover_url}/#/apps/details/{app_name}")
page.wait_for_timeout(3000)
```

### 3. Force Build (Deployment tab)

```python
page.locator("text=Deployment").first.click()
page.wait_for_timeout(2000)

force = page.locator("button:has-text('Force Build')")
if not force.is_disabled():
    force.click()
```

If Force Build is disabled, click Save & Restart first:
```python
saves = page.locator("button:has-text('Save & Restart')")
for i in range(saves.count()):
    btn = saves.nth(i)
    if not btn.is_disabled():
        btn.click()
        break
```

### 4. HTTP Settings (HTTPS + WebSocket)

```python
page.locator("text=HTTP Settings").first.click()
page.wait_for_timeout(2000)

# Enable HTTPS
https_btn = page.locator("button:has-text('Enable HTTPS')")
if https_btn.count() > 0 and not https_btn.is_disabled():
    https_btn.click()
    page.wait_for_timeout(15000)  # Cert generation takes time

# Enable WebSocket
ws = page.locator("text=WebSocket Support")
if ws.count() > 0:
    ws.click()

# Save
saves = page.locator("button:has-text('Save & Restart')")
for i in range(saves.count()):
    btn = saves.nth(i)
    if not btn.is_disabled():
        btn.click()
        break
```

### 5. Poll build status (via API)

Use the REST API to check build completion — more reliable than scraping the dashboard:

```python
for attempt in range(30):
    time.sleep(10)
    data = api.get_build_status(app_name)
    if not data.get("isAppBuilding"):
        if data.get("isBuildFailed"):
            print("Build failed!")
        else:
            print("Build succeeded!")
        break
```

## Localization Notes

CapRover dashboard may be in English or Portuguese depending on browser locale. The deploy script tries both:

| English | Portuguese |
|---------|-----------|
| Deployment | Implantação |
| Force Build | Forçar build |
| Save & Restart | Salvar & Reiniciar |
| Enable HTTPS | Habilitar HTTPS |
| WebSocket Support | Suporte a Websocket |
| HTTP Settings | Configurações HTTP |

## Common Issues

- **Ant Design buttons** may not respond to accessibility-tree clicks from some browser automation tools. Playwright's `locator().click()` handles this correctly.
- **HTTPS cert generation** takes 10-30 seconds. Always `wait_for_timeout(15000)` after clicking Enable HTTPS.
- **Headless mode** works fine — no need for a visible browser window.
