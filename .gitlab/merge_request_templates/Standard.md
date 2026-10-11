## Was und warum

<!-- Ein, zwei Sätze: Was ändert sich für Nutzer, und warum? Roadmap-Nummer (GA-…), falls es eine gibt. -->

## Geprüft

- [ ] `PYTHONUTF8=1 python -m pytest -q` grün (Unit-Tests in `tests/`)
- [ ] `python -m ruff check .` sauber
- [ ] Bei Änderungen an Setup, Entitäten, Services oder MQTT: Tests gegen ein echtes Home Assistant (`pytest -c pytest-ha.ini`, `tests_ha/`)
- [ ] Neue Abhängigkeit: in `manifest.json` bzw. der passenden `worker/requirements-*.txt`, und in `requirements-test.txt`, falls die Tests sie brauchen

## Mitgezogen

- [ ] `CHANGELOG.md` unter `[Unreleased]` (Englisch)
- [ ] `ROADMAP.md`: Status der Aufgabe (Deutsch)
- [ ] README oder `docs/` bei sichtbaren Änderungen
- [ ] Neue Entität oder Option: `strings.json` und alle fünf `translations/*.json`
- [ ] Neuer Service: `services.yaml` und `_ALL_SERVICES` in `__init__.py`
- [ ] Keine Tokens, Passwörter oder internen Adressen im Diff

<!-- Gemergt wird nur bei grüner Pipeline; ein Merge geht automatisch nach GitHub. Ein Release (Tag) nur mit Chris' Ja, siehe docs/release_checkliste.md. -->
