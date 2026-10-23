// Bildschirmfotos für das Handbuch (Anweisung 06 › „docs:bilder“). Nur Testdaten (?demo),
// nie echte Daten. Feste Dateinamen in docs/handbuch/bilder/.
//
//   npm i --no-save playwright@1 && npx playwright install chromium   # einmalig
//   node werkzeuge/bilder.mjs
//
// Startet zwei Monitore auf 127.0.0.1 in einem Wegwerf-Ordner: einen im Entwicklungsmodus
// (Dashboard mit Demo-Daten) und einen normalen für Einrichtung und Anmeldung.
// Als normaler Benutzer ausführen – der Monitor startet nicht als root.
import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright';

const WURZEL = resolve(new URL('..', import.meta.url).pathname);
const ZIEL = join(WURZEL, 'docs/handbuch/bilder');
const tmp = mkdtempSync(join(tmpdir(), 'rm-bilder-'));
mkdirSync(ZIEL, { recursive: true });
for (const d of ['dev', 'daten', 'lauf']) mkdirSync(join(tmp, d), { recursive: true });

writeFileSync(join(tmp, 'daten/systempruefung.json'), JSON.stringify({
  zeit: Date.now() / 1000, vm: 'runner-vm', port: 8090, monitorVersion: '0.1.0',
  runner: { gefunden: true, name: 'runner-vm-01', version: '2.329.0', dienst: 'actions.runner.beispiel-org.runner-vm-01.service' },
  firewall: { aktiv: true },
}));
execFileSync('python3', ['-c', `import pathlib; from runner_monitor import zugang; zugang.schreibe_code(pathlib.Path(${JSON.stringify(join(tmp, 'daten/einrichtungscode.json'))}), 'ABCD-2345')`], { cwd: WURZEL });

const starte = (port, env) => spawn('python3', ['-m', 'runner_monitor'], {
  cwd: WURZEL, stdio: 'ignore',
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', MONITOR_ADRESSE: '127.0.0.1', MONITOR_PORT: String(port), MONITOR_WEB_VERZ: join(WURZEL, 'web'), MONITOR_LAUF_VERZ: join(tmp, 'lauf'), ...env },
});
const dienste = [
  starte(18091, { MONITOR_ENTWICKLUNG: '1', MONITOR_DATEN_VERZ: join(tmp, 'dev') }),
  starte(18092, { MONITOR_DATEN_VERZ: join(tmp, 'daten') }),
];
await new Promise(r => setTimeout(r, 1500));

const browser = await chromium.launch(process.env.CHROME ? { executablePath: process.env.CHROME } : {});
async function seite({ breite = 1440, hoehe = 900, dunkel = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: breite, height: hoehe }, colorScheme: dunkel ? 'dark' : 'light', locale: 'de-DE', timezoneId: 'Europe/Berlin' });
  return ctx.newPage();
}
const D = 'http://127.0.0.1:18091/?demo&leiste=0', E = 'http://127.0.0.1:18092';
const bild = (p, name) => p.screenshot({ path: join(ZIEL, name) });

try {
  let p = await seite();
  await p.goto(D); await p.waitForTimeout(5000); await bild(p, 'dashboard-job.png');
  await p.click('#k-info'); await p.waitForTimeout(600); await bild(p, 'info-hilfe.png');
  p = await seite({ dunkel: true });
  await p.goto(`${D}&zustand=volllast&kerne=16`); await p.waitForTimeout(4000); await bild(p, 'dashboard-volllast-dunkel.png');
  p = await seite();
  await p.goto(`${D}&zustand=gestoppt`); await p.waitForTimeout(2500); await bild(p, 'dashboard-gestoppt.png');
  await p.click('.meldung-link'); await p.waitForTimeout(600); await bild(p, 'was-tun-gestoppt.png');
  p = await seite();
  await p.goto(`${D}&zustand=platte&github=ablauf`); await p.waitForTimeout(2500); await bild(p, 'dashboard-platte-knapp.png');
  p = await seite();
  await p.goto(`${D}&zustand=leerlauf&github=kein-token`); await p.waitForTimeout(2500); await bild(p, 'dashboard-kein-token.png');
  p = await seite();
  await p.goto(`${D}&zustand=leerlauf&update=verfuegbar`); await p.waitForTimeout(2000);
  await p.click('.meldung-link'); await p.waitForTimeout(400); await p.evaluate(() => document.querySelector('.info-body').scrollTo(0, 0)); await bild(p, 'update-verfuegbar.png');

  p = await seite();
  await p.goto(E + '/'); await p.waitForSelector('#code'); await bild(p, 'einrichtung-1-code.png');
  await p.fill('#code', 'ABCD2345'); await p.click('button[type=submit]'); await p.waitForSelector('#pw'); await bild(p, 'einrichtung-2-zugang.png');
  await p.fill('#nutzer', 'verwaltung'); await p.fill('#pw', 'ein langer satz zum merken'); await p.fill('#pw2', 'ein langer satz zum merken');
  await p.click('button[type=submit]'); await p.waitForSelector('#org'); await bild(p, 'einrichtung-3-github.png');
  await p.click('#ueberspringen'); await p.waitForSelector('#zum-monitor'); await bild(p, 'einrichtung-4-fertig.png');
  await p.click('#zum-monitor'); await p.waitForSelector('#passwort'); await bild(p, 'anmelden.png');
  await p.fill('#nutzer', 'verwaltung'); await p.fill('#passwort', 'falsches passwort'); await p.click('#absenden'); await p.waitForTimeout(800); await bild(p, 'anmelden-fehler.png');
  p = await seite({ breite: 390, hoehe: 844 });
  await p.goto(E + '/anmelden'); await p.waitForSelector('#passwort'); await bild(p, 'anmelden-telefon.png');
  console.log(`Bilder in ${ZIEL}`);
} finally {
  await browser.close();
  dienste.forEach(d => d.kill());
}
