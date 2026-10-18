# 🦅 Dissuasore piccioni

App Docker per Raspberry Pi che riproduce versi di uccelli predatori (falco pellegrino, astore, gufo reale…) dall'uscita cuffie, a intervalli casuali e nelle fasce orarie che scegli. Si controlla da un'interfaccia web.

## Cosa fa

- **Stato**: attivo / fuori orario / disattivato, tempo al prossimo verso, cosa sta suonando.
- **Comandi**: riproduci un verso casuale, ferma, attiva/disattiva il funzionamento automatico.
- **Versi**: elenco, anteprima nel browser, riproduzione sulle cuffie del Pi, caricamento (trascina e rilascia, mp3/wav/ogg), eliminazione, esclusione temporanea di un verso.
- **Sessioni di disturbo**: per alcuni minuti (es. 5-10) suonano versi diversi a pause casuali (es. 20-60 s), come un predatore che gira nei dintorni; poi una pausa lunga casuale (es. 30-90 min) prima della sessione successiva. Il pulsante **Avvia sessione ora** ne fa partire una subito; con durata sessione 0 suona un solo verso alla volta.
- **Programmazione**: più fasce orarie (anche a cavallo della mezzanotte), giorni della settimana, volume, durata massima di un verso.
- **Registro e statistiche**: ultime riproduzioni con esito ed eventuali errori, conteggi di oggi / 7 giorni / totale, grafico per ora del giorno, quante volte è stato usato ogni verso.

Lo stesso verso non viene mai ripetuto due volte di fila e tutte le pause sono casuali: i piccioni si abituano in fretta ai suoni regolari. Concentra le fasce orarie nei momenti in cui arrivano (di solito l'alba) e usa un altoparlante amplificato: le cuffie all'aperto si sentono appena.

## Requisiti

- Raspberry Pi 3 con Raspberry Pi OS (32 o 64 bit), cuffie o altoparlante nel jack audio.
- Docker con il plugin compose:

  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER   # poi esci e rientra
  ```

## Installazione

L'immagine Docker viene costruita automaticamente da GitHub Actions a ogni modifica su `main` e pubblicata su GitHub Packages come `ghcr.io/land2595/dissuasore-piccioni:latest` (per Raspberry Pi a 32 e 64 bit e per PC). Sul Pi non serve compilare nulla.

1. Sul Pi scarica solo il file di avvio e avvia:

   ```bash
   mkdir -p ~/dissuasore-piccioni && cd ~/dissuasore-piccioni
   curl -fsSLO https://raw.githubusercontent.com/land2595/dissuasore-piccioni/main/docker-compose.yml
   docker compose up -d
   ```

   (Oppure clona l'intero repository con `git clone`.)
2. Apri `http://<ip-del-pi>:8080` dal telefono o dal PC.

Se il repository o il pacchetto sono privati, prima fai `docker login ghcr.io -u land2595` usando come password un token GitHub con permesso `read:packages`; in alternativa rendi pubblico il pacchetto da GitHub → profilo → *Packages* → *dissuasore-piccioni* → *Package settings*. Per i file privati anche il `curl` richiede autenticazione: in quel caso usa `git clone`.

Per costruire l'immagine direttamente sul Pi, in `docker-compose.yml` commenta `image:`, togli il commento a `build: .` e usa `docker compose up -d --build`.

Suoni, impostazioni e registro sono salvati in `./data` e sopravvivono a riavvii e aggiornamenti. Il container riparte da solo all'accensione del Pi (`restart: unless-stopped`).

## Configurare l'audio

Le impostazioni predefinite puntano al jack cuffie del Pi:

| Campo | Valore predefinito |
|---|---|
| Dispositivo ALSA | `plughw:CARD=Headphones,DEV=0` |
| Controllo mixer | `PCM` |
| Scheda mixer | `Headphones` |

Per verificarle:

1. Nella sezione **Impostazioni** premi **🔊 Prova audio**: deve sentirsi un beep di un secondo.
2. Se non senti nulla, premi **Mostra dispositivi audio** e cerca la riga con `Headphones` (o `bcm2835`). Inserisci il nome mostrato nella forma `plughw:CARD=<nome>,DEV=0`, salva e riprova.
3. Se compare "volume non impostato", controlla il nome del controllo mixer sul Pi con `amixer -c Headphones scontrols` (di solito `PCM` oppure `Headphone`).

Verifiche dal terminale del Pi, fuori da Docker:

```bash
aplay -l                                   # elenca le schede audio
speaker-test -D plughw:CARD=Headphones,DEV=0 -c 2 -t wav -l 1
```

Se l'audio esce dall'HDMI invece che dalle cuffie, usa `sudo raspi-config` → *System Options* → *Audio* e scegli *Headphones*. L'app comunque usa il dispositivo indicato nelle impostazioni.

## Problemi noti

**Il container si chiude subito con `PermissionError: [Errno 1] Operation not permitted`** (in `time.get_clock_info`). Capita su Raspberry Pi OS a 32 bit quando Docker o `libseccomp2` sono troppo vecchi e bloccano le chiamate di sistema dell'orologio a 64 bit. Soluzioni:

1. Consigliata: aggiorna con `sudo apt update && sudo apt install --only-upgrade libseccomp2 docker-ce` (serve libseccomp2 2.4.4 o più recente; su Buster non c'è, meglio passare a Bookworm).
2. Rapida: in `docker-compose.yml` togli il commento a `security_opt: - seccomp:unconfined` e riavvia.

## Dove trovare i versi

Cerca registrazioni di falco pellegrino (Falco peregrinus), astore (Accipiter gentilis), gufo reale (Bubo bubo) e sparviere (Accipiter nisus), più il richiamo d'allarme del piccione (Columba livia, "alarm call"), su siti con licenze libere, ad esempio [xeno-canto.org](https://xeno-canto.org) (controlla la licenza di ogni file) o Freesound. File brevi (5-20 secondi) e diversi tra loro funzionano meglio.

Nell'interfaccia puoi anche incollare il link di una registrazione xeno-canto (per esempio `https://xeno-canto.org/123456`) o un link diretto a un file mp3/wav/ogg e premere **Aggiungi da link**: il Pi scarica il file da solo.

## Protezione con password

In `docker-compose.yml` togli il commento a `WEB_USER` e `WEB_PASSWORD`, scegli le credenziali e riavvia con `docker compose up -d`. Il browser chiederà utente e password. Non esporre la porta 8080 su Internet senza password.

## Comandi utili

```bash
docker compose logs -f          # log in tempo reale
docker compose restart          # riavvio
docker compose down             # arresto
docker compose pull && docker compose up -d   # aggiorna all'ultima versione
```

## Variabili d'ambiente

| Variabile | Default | Significato |
|---|---|---|
| `TZ` | `Europe/Rome` | Fuso orario delle fasce orarie |
| `WEB_USER` / `WEB_PASSWORD` | vuote | Attivano la password sull'interfaccia |
| `MAX_UPLOAD_MB` | `20` | Dimensione massima di un file caricato |
| `DISSUASORE_DRY_RUN` | `0` | Con `1` simula la riproduzione (per provare l'app su un PC senza audio) |

## API

L'interfaccia usa un'API JSON che puoi chiamare anche da Home Assistant o da script:

- `GET /api/status`: stato e statistiche
- `POST /api/play` con `{"name": "falco.mp3"}` oppure `{}` per un verso casuale
- `POST /api/stop` (ferma anche la sessione in corso)
- `POST /api/session/start`
- `GET /api/sounds`, `POST /api/sounds` (multipart, campo `files`), `POST /api/sounds/from-url` con `{"url": "..."}`, `DELETE /api/sounds/{nome}`
- `GET /api/config`, `PUT /api/config` (per esempio `{"enabled": false}`)
- `GET /api/log`

Documentazione interattiva completa su `http://<ip-del-pi>:8080/docs`.

## Struttura

```
app/main.py        API web
app/player.py      riproduzione (aplay per wav, mpg123 per mp3, ogg123 per ogg) e volume (amixer)
app/scheduler.py   programmazione casuale nelle fasce orarie
app/store.py       impostazioni (data/config.json) e registro (data/log.db)
app/static/        interfaccia web
```
