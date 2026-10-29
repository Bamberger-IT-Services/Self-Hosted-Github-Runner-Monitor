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
import { mkdtempSync, writeFileSync, mkdirSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { chromium } from 'playwright';

const WURZEL = resolve(new URL('..', import.meta.url).pathname);
const ZIEL = join(WURZEL, 'docs/handbuch/bilder');
const tmp = mkdtempSync(join(tmpdir(), 'rm-bilder-'));
mkdirSync(ZIEL, { recursive: true });
for (const d of ['dev', 'daten', 'lauf']) mkdirSync(join(tmp, d), { recursive: true });
// Einrichtung (#96): ein erkannter GitHub-Runner und ein unbekannter Dienst, nur Platzhalter-Namen
mkdirSync(join(tmp, 'actions-runner'), { recursive: true });
writeFileSync(join(tmp, 'actions-runner/.runner'), JSON.stringify({ agentName: 'runner-vm-01', gitHubUrl: 'https://github.com/beispiel-org' }));
const faehig = (jobs) => ({ status: true, jobs, schritte: jobs, logs: true, updates: false });
writeFileSync(join(tmp, 'lauf/erkennung.json'), JSON.stringify({ zeit: Date.now() / 1000, geprueft: [], runner: [
  { id: 'runner-vm-01', name: 'runner-vm-01', dienst: 'github', server: 'https://github.com/beispiel-org', version: '2.329.0', grad: 'sicher',
    merkmale: ['systemd-Unit actions.runner.beispiel-org.runner-vm-01.service', '/opt/actions-runner/.runner mit gitHubUrl', 'Prozess Runner.Listener läuft'],
    einstufung: 'voll', stand: 'offen', unit: 'actions.runner.beispiel-org.runner-vm-01.service', log: null, faehig: faehig(true), aktiv: true, grund: null },
  { id: 'buildagent', name: 'buildagent', dienst: 'unbekannt', server: null, version: null, grad: 'unklar',
    merkmale: ['Dienst buildagent.service', 'Name enthält „agent“', 'startet Container'],
    einstufung: 'unbekannt', stand: 'offen', unit: 'buildagent.service', log: null, faehig: faehig(false), aktiv: true, grund: null },
] }));

writeFileSync(join(tmp, 'daten/systempruefung.json'), JSON.stringify({
  zeit: Date.now() / 1000, vm: 'runner-vm', port: 8090, monitorVersion: readFileSync(join(WURZEL, 'VERSION'), 'utf8').trim(),
  runner: { gefunden: true, name: 'runner-vm-01', version: '2.329.0', dienst: 'actions.runner.beispiel-org.runner-vm-01.service', aktiv: true },
  firewall: { aktiv: true, netz: '192.0.2.0/24' },
}));
execFileSync('python3', ['-c', `import pathlib; from runner_monitor import zugang; zugang.schreibe_code(pathlib.Path(${JSON.stringify(join(tmp, 'daten/einrichtungscode.json'))}), 'ABCD-2345')`], { cwd: WURZEL });

const starte = (port, env) => spawn('python3', ['-m', 'runner_monitor'], {
  cwd: WURZEL, stdio: 'ignore',
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', MONITOR_ADRESSE: '127.0.0.1', MONITOR_PORT: String(port), MONITOR_WEB_VERZ: join(WURZEL, 'web'), MONITOR_LAUF_VERZ: join(tmp, 'lauf'), ...env },
});
const dienste = [
  starte(18091, { MONITOR_ENTWICKLUNG: '1', MONITOR_DATEN_VERZ: join(tmp, 'dev') }),
  starte(18092, { MONITOR_DATEN_VERZ: join(tmp, 'daten'), MONITOR_RUNNER_VERZ: join(tmp, 'actions-runner'), MONITOR_TOKEN_DATEI: join(tmp, 'etc/github-token'), MONITOR_ORG: 'beispiel-org', MONITOR_VM_NAME: 'runner-vm' }),
];
await new Promise(r => setTimeout(r, 1500));

const browser = await chromium.launch(process.env.CHROME ? { executablePath: process.env.CHROME } : {});
async function seite({ breite = 1440, hoehe = 900, dunkel = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width: breite, height: hoehe }, colorScheme: dunkel ? 'dark' : 'light', locale: 'de-DE', timezoneId: 'Europe/Berlin' });
  return ctx.newPage();
}
const D = 'http://127.0.0.1:18091/?demo&leiste=0', E = 'http://127.0.0.1:18092';
// Kurz warten: Einblendungen (0,35 s) und Abfragen wie /api/health sollen fertig sein
const bild = async (p, name) => { await p.waitForTimeout(700); await p.screenshot({ path: join(ZIEL, name) }); };

try {
  let p = await seite();
  await p.goto(D); await p.waitForTimeout(5000); await bild(p, 'dashboard-job.png');
  await p.click('#k-info'); await p.waitForTimeout(600); await bild(p, 'info-hilfe.png');
  p = await seite({ dunkel: true });
  await p.goto(`${D}&zustand=volllast&kerne=16`); await p.waitForTimeout(4000); await bild(p, 'dashboard-volllast-dunkel.png');
  p = await seite();
  // Design 0.4.0: kurz nach einem Neustart („seit hh:mm“) und ohne Schrittliste von GitHub („3 von –“)
  await p.goto(`${D}&zustand=job&verlauf=150&schritte=lokal`); await p.waitForTimeout(4000); await bild(p, 'dashboard-neustart.png');
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
  await p.click('button[type=submit]'); await p.waitForSelector('.fund'); await bild(p, 'einrichtung-3-runner.png');
  await p.click('button[type=submit]'); await p.waitForSelector('[data-aktion="ohne-anbindung"]'); await bild(p, 'einrichtung-4-anbinden.png');
  await p.click('[data-aktion="ohne-anbindung"]'); await p.waitForSelector('#zum-monitor'); await bild(p, 'einrichtung-5-fertig.png');
  await p.click('#zum-monitor'); await p.waitForSelector('#passwort'); await bild(p, 'anmelden.png');
  await p.fill('#nutzer', 'verwaltung'); await p.fill('#passwort', 'falsches passwort'); await p.click('#absenden'); await p.waitForTimeout(800); await bild(p, 'anmelden-fehler.png');
  p = await seite({ breite: 390, hoehe: 844 });
  await p.goto(E + '/anmelden'); await p.waitForSelector('#passwort'); await bild(p, 'anmelden-telefon.png');
  console.log(`Bilder in ${ZIEL}`);
} finally {
  await browser.close();
  dienste.forEach(d => d.kill());
}
