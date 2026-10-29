/* Links in die Doku (docs/*.md im öffentlichen Quellcode, #132, E-28). Sie zeigen auf den Tag der
   laufenden Version (blob/v<VERSION>), damit Anleitung und installierte Version zusammenpassen; ohne
   bekannte Release-Version (leer, Entwicklungsstand, „-dev“) auf main. Reine Logik ohne DOM, damit sie
   sich mit node prüfen lässt (tests/js/doku.test.mjs). Im Browser als globales DOKU. */
'use strict';

const DOKU = (() => {
  const BASIS = 'https://github.com/Bamberger-IT-Services/Self-Hosted-Github-Runner-Monitor/blob/';
  const RELEASE = /^\d+\.\d+\.\d+$/;
  let version = '';

  const setzeVersion = (v) => { version = RELEASE.test(String(v || '').trim()) ? String(v).trim() : ''; };
  /* datei: Name unter docs/ (z. B. „EINRICHTUNG.md“), anker: Überschrift-Anker ohne „#“ */
  const url = (datei, anker) => `${BASIS}${version ? `v${version}` : 'main'}/docs/${datei}${anker ? `#${anker}` : ''}`;

  return { BASIS, setzeVersion, url };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = DOKU;
