# Full gas DES COM 1

Il sito della classe di Design della Comunicazione, IED Torino, primo anno 2026/27.

## Come funziona
- `template.html` è la grafica del sito.
- `data.json` contiene i dati: lezioni, materie, avvisi, documenti, domande.
- `scripts/update.py` ogni ora scarica l'orario IED e, se è impostato il segreto `NOTION_TOKEN`, legge Notion. Poi genera il sito.
- `.github/workflows/update.yml` fa partire l'aggiornamento ogni ora e pubblica il sito su GitHub Pages.

## Aggiornare subito
Actions → "Aggiorna il sito" → Run workflow.

## Cambiare i contenuti
Si cambiano su Notion (pagina CLASS OFFICE.): materie, scadenze, avvisi, documenti, domande. Il sito si aggiorna entro un'ora.
