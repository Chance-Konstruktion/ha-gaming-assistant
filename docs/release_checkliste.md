# Release-Checkliste

Ein Release ist der Moment, in dem HACS-Nutzer etwas Neues bekommen. Deshalb
gibt es ein Release nur mit Chris' Ja. Entwickelt wird im GitLab; GitHub ist
die Installationsquelle für HACS und bekommt `main` und die Tags über den
Push-Spiegel.

## Der Weg eines Releases

1. Der Tag `v<version>` entsteht im **GitLab**, nie auf GitHub.
2. Die GitLab-Pipeline des Tags testet und legt dann zwei Releases an:
   `release` im GitLab und `github-release` auf GitHub. Der zweite Job braucht
   die CI-Variable `GITHUB_TOKEN` und schreibt nur einen Platzhaltertext.
3. Der Spiegel bringt den Tag nach GitHub. Dort baut
   `.github/workflows/release.yml` das HACS-Zip und setzt als Text den
   Abschnitt der Version aus `CHANGELOG.md` (`tools/changelog_section.py`).
   Es ist egal, wer zuerst fertig ist: Ist das Release schon da, ersetzt der
   Workflow den Platzhalter und hängt das Zip an; sonst legt er es an, und
   `github-release` meldet „gibt es bereits“.
4. HACS installiert aus dem GitHub-Release (`hacs.json`: `zip_release: false`,
   also den Quellstand des Tags).

Nur Tags mit `v` lösen den GitHub-Workflow aus. Ein Tag wie `260619` ohne `v`
bekommt kein Zip und keinen CHANGELOG-Text.

## Vorher

- [ ] `main` ist grün: GitLab-Pipeline und GitHub-CI (Unit-Tests, Ladetest
      gegen die Mindestversion von Home Assistant, Validate).
- [ ] Version festlegen: Datum des Releases als `JJMMTT`, z. B. `261012`.
- [ ] `custom_components/gaming_assistant/manifest.json`: `"version"` auf
      diese Version.
- [ ] `CHANGELOG.md`: Aus `## [Unreleased]` wird
      `## [<version>] - JJJJ-MM-TT — "Titel"`; darüber kommt ein neues, leeres
      `## [Unreleased]`.
- [ ] `ROADMAP.md`: „(unreleased)“ wird zu „v<version>“, Teststand und
      Stakeholder-Kurzfassung aktualisieren.
- [ ] README: Stimmen Mindestversionen (`hacs.json`), Installationsschritte
      und die Beschreibung neuer Funktionen?
- [ ] `python tools/changelog_section.py v<version>` zeigt den richtigen Text.
- [ ] Diese Änderungen gehen als eigener MR rein und werden bei grüner
      Pipeline gemergt.

## Release

- [ ] Chris hat Ja gesagt.
- [ ] Tag auf den Merge-Commit in `main` setzen und pushen, **ohne**
      `-o ci.skip`, sonst laufen die Release-Jobs nicht:

  ```bash
  git tag -a v<version> -m "v<version>"
  git push origin v<version>
  ```
- [ ] Nur diesen einen Tag pushen. Kommen mehr als drei Tags in einem Push an,
      löst GitHub keine Ereignisse aus, und das Zip fehlt.

## Danach

- [ ] GitLab: Pipeline des Tags grün, auch `release` und `github-release`.
- [ ] GitHub: Release `v<version>` ist sichtbar, als „Latest“ markiert, mit
      `gaming_assistant_hacs.zip` und dem CHANGELOG-Text.
- [ ] HACS zeigt die neue Version (notfalls in HACS „Update information“).
- [ ] Auf einem Test-Home-Assistant über HACS aktualisieren, neu starten und
      prüfen, dass die Integration lädt.

## Niemals

- **Tags im GitLab löschen oder umbenennen.** Der Spiegel löscht GitHub-Tags,
  die im GitLab fehlen. Mit dem Tag verschwindet das Release aus der Liste, und
  HACS fällt auf `main` zurück. So sind am 08.10.2026 `v260619` und `v0.11.0`
  kurz verschwunden.
- **Auf GitHub taggen.** Der Tag fehlt im GitLab, also löscht ihn der nächste
  Spiegel-Lauf wieder.
- **Ein Release ohne CHANGELOG-Abschnitt.** Der Workflow bricht dann zwar
  nicht ab, aber auf GitHub steht nur ein Verweis statt der Neuerungen.
