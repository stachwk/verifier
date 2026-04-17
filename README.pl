# Verifier

Verifier to prosty system do przypisywania kluczy sesji i credentiali do konkretnych
programów. Każda instancja programu jest identyfikowana przez:

- `hash` pliku programu
- `instance_key`, czyli klucz instancji

Ten sam plik może więc mieć wiele niezależnych instancji, a każda z nich może mieć
własny klucz sesji i własne credentiale.

## Idea i sens

Verifier rozwiązuje praktyczny problem: jak przypisać sekret do konkretnego programu
w taki sposób, żeby nie wystarczała sama nazwa pliku, katalog albo ręcznie wpisany
identyfikator.

Najpierw program potwierdza swoją tożsamość hashem pliku. Potem potwierdza konkretną
instancję, bo ten sam kod może działać równolegle w kilku środowiskach. Dopiero wtedy
może pobrać przypisany credential.

To daje trzy ważne własności:

- sekret jest przypisany do rzeczywistego pliku programu, nie do jego nazwy
- wiele instancji tego samego programu może mieć różne klucze sesji i różne credentiale
- każda poprawna autoryzacja odświeża klucz sesji, więc poprzedni stan nie zostaje
  ważny na zawsze

W praktyce Verifier łączy trzy rzeczy: tożsamość programu, tożsamość instancji i
powiązany sekret.

## Przepływ od początku do końca

Najprościej zrozumieć Verifiera, uruchamiając cały przepływ raz.

### 1. Przygotuj konfigurację

Upewnij się, że `verifier_cfg.ini` wskazuje bazę i pliki kluczy:

```ini
[paths]
DB_NAME = verifier.db
DB_KEY_FILE = verifier-db_key.key
SECRET_KEY_FILE = verifier-secret.key
```

Jeśli chcesz logi do pliku, włącz je:

```ini
[main]
LOG = 1
```

### 2. Utwórz bazę

```bash
python3.12 verifier_cli.py --config ./verifier_cfg.ini --create-db
```

To tworzy tabele potrzebne do programów, credentiali i ich powiązań.

### 3. Autoryzuj instancję programu

```bash
python3.12 verifier_cli.py --config ./verifier_cfg.ini --authorize test_program ./test/unit/test_program.py 1
```

To polecenie robi cztery rzeczy:

- liczy hash `./test/unit/test_program.py`
- zapisuje nazwę programu, hash i `instance_key`
- generuje klucz sesji dla tej konkretnej instancji
- tworzy plik `test_program_1.key` obok pliku programu

Jeśli obecne są `cert.pem` i `key.pem`, muszą tworzyć poprawną parę administratora.

### 4. Dodaj i podłącz credential

```bash
python3.12 verifier_cli.py --config ./verifier_cfg.ini --add-pwd-cmd ./test/unit/test_program.py database read_only Secret123 1
```

To tworzy credential z:

- `context = database`
- `subcontext = read_only`
- hasłem credentiala `Secret123`

Następnie przypisuje ten credential do tego samego hasha programu i tego samego
`instance_key`.

### 5. Uruchom program

```bash
python3.12 test/unit/test_program.py 1 ./verifier_cfg.ini
```

Program potem:

- czyta stary klucz sesji z `test_program_1.key`
- uwierzytelnia się w bazie
- dostaje nowy klucz sesji
- aktualizuje plik klucza sesji
- czyta powiązany credential `database/read_only`

### 6. Jak wygląda sukces

Jeśli wszystko działa poprawnie, w outputcie zobaczysz, że:

- program został rozpoznany po hashu i `instance_key`
- stary klucz sesji został zaakceptowany
- wygenerowano nowy klucz sesji
- plik klucza sesji został zaktualizowany
- zwrócono powiązany credential

## Pełny przykład

```bash
python3.12 verifier_cli.py --config ./verifier_cfg.ini --create-db
python3.12 verifier_cli.py --config ./verifier_cfg.ini --authorize test_program ./test/unit/test_program.py 1
python3.12 verifier_cli.py --config ./verifier_cfg.ini --add-pwd-cmd ./test/unit/test_program.py database read_only Secret123 1
python3.12 test/unit/test_program.py 1 ./verifier_cfg.ini
```

Dla szybszego bootstrapu możesz użyć:

```bash
./bootstrap_program_secret.sh example_program ./test/scenario/scenario_program_using_verifier.py 1 database read_only Secret123
```

Albo zrobić bootstrap i od razu uruchomić scenariusz:

```bash
./bootstrap_and_run_scenario.sh example_program 1 database read_only Secret123
```

## Jak to działa

1. Uruchamiasz `--create-db`, aby utworzyć tabele w bazie.
2. Uruchamiasz `--authorize`, podając nazwę programu, ścieżkę do pliku i `instance_key`.
   To polecenie wymaga poprawnej pary administratora `cert.pem` / `key.pem`.
3. CLI zapisuje:
   - hash programu w bazie
   - klucz sesji dla tej instancji
   - plik `<program_name>_<instance_key>.key`
4. Możesz dodać credential, na przykład hasło credentiala do bazy danych.
5. Następnie przypisujesz ten credential do konkretnego programu i konkretnej instancji.
6. Program testowy uruchomiony dla tej samej instancji może:
   - odczytać poprzedni klucz sesji z katalogu programu
   - potwierdzić autoryzację
   - wygenerować nowy klucz sesji i podmienić plik klucza sesji
   - pobrać credential przypisany do tego programu

## Ważna zasada

Sam hash programu nie wystarczy.
Żeby pobrać credential, program musi być:

- autoryzowany w bazie dla konkretnego `instance_key`
- powiązany z credentialem
- uruchomiony z poprawnym plikiem klucza sesji

## Dlaczego to jest tak zbudowane

Ten układ chroni przed kilkoma typowymi problemami:

- samą nazwę pliku da się łatwo skopiować
- sam hash nie rozróżnia środowisk uruchomieniowych
- pojedynczy wspólny sekret dla wszystkich instancji szybko przestaje być wygodny
- ręczne trzymanie haseł w plikach bez kontroli prowadzi do chaosu

Verifier daje prosty kompromis:

- baza przechowuje zaszyfrowane dane
- program ma lokalny plik klucza sesji, który można odświeżać
- przypisanie credentiala jest jawne i zależne od konkretnej instancji

To nie jest pełny system zarządzania sekretami klasy enterprise.
To jest mały, zrozumiały mechanizm do scenariuszy, w których program sam ma
potwierdzić swoją tożsamość i dostać tylko te dane, które zostały mu przypisane.

## Jak powinien wyglądać program

Program korzystający z Verifiera powinien mieć prosty układ:

1. Odczytujesz `instance_key` z argumentów wiersza poleceń.
2. Budujesz `key_path` z katalogu programu i czytasz z niego stary klucz sesji.
3. Tworzysz obiekt `Verifier(program_path, config_file="/sciezka/do/verifier_cfg.ini")`, żeby program sam policzył swój hash.
4. Wywołujesz `authenticate_and_regenerate(old_pass, instance_key)`.
5. Jeśli autoryzacja się uda, możesz wywołać `get_context_password(...)`.
6. Nowy klucz sesji zapisany przez Verifiera nadpisuje stary plik klucza sesji.

Minimalny szkielet:

```python
from verifier import Verifier
import sys
import os

def main():
    instance_key = sys.argv[1]
    program_path = os.path.abspath(__file__)
    key_path = os.path.join(os.path.dirname(program_path), f"test_program_{instance_key}.key")

    with open(key_path, "r") as f:
        old_pass = f.read().strip()

    verifier = Verifier(program_path, config_file="/sciezka/do/verifier_cfg.ini")
    success, new_pass = verifier.authenticate_and_regenerate(old_pass, instance_key)
    if not success:
        return

    db_password = verifier.get_context_password("database", "read_only")
    print(db_password)

if __name__ == "__main__":
    main()
```

Ważne:

- `Verifier(__file__)` oznacza, że hash liczony jest z aktualnego pliku programu.
- `config_file` pozwala wskazać Verifierowi inną lokalizację `verifier_cfg.ini`.
- Ten sam plik uruchomiony z innym `instance_key` jest traktowany jako osobna instancja.
- Credentiale są zwracane dopiero po udanej autoryzacji.
- Jeśli plik programu się zmieni, hash się zmieni i istniejący rekord nie będzie pasował.

## Główne pliki

- `verifier.py` - logika bazy, szyfrowania i autoryzacji
- `verifier_cli.py` - CLI do tworzenia bazy, autoryzacji i zarządzania credentialami
- `test/runtime_utils.py` - wspólne helpery dla skryptów test/example/scenario
- `test/unit/test_program.py` - przykładowy program testowy, który używa przypisanego klucza
- `bootstrap_program_secret.sh` - prosty bootstrap w shellu do autoryzacji i podpięcia sekretu
- `bootstrap_and_run_scenario.sh` - bootstrap i natychmiastowe uruchomienie scenariusza
- `test/example/example_program_using_verifier.py` - przykład w Pythonie, który uwierzytelnia się i czyta sekret
- `test/scenario/scenario_program_using_verifier.py` - scenariusz w Pythonie, który odnawia klucz sesji i czyta przypisany sekret
- `test/README.md` - opis podziału katalogu testowego

## Wymagania

- Python 3.12 (projekt był testowany na Pythonie 3.12.x)
- `cryptography`
- `pysqlcipher3`
- `cffi` jako zależność pomocnicza `cryptography`

Przykładowa instalacja:

```bash
python3.12 -m pip install cryptography pysqlcipher3 cffi
```

## Licencja

Projekt jest udostępniony na licencji MIT. Pełny tekst znajduje się w pliku [LICENSE](LICENSE).

## Konfiguracja projektu

Plik `verifier_cfg.ini` powinien zawierać co najmniej:

```ini
[paths]
DB_NAME = verifier.db
DB_KEY_FILE = verifier-db_key.key
SECRET_KEY_FILE = verifier-secret.key
```

Jeśli chcesz włączyć logowanie do plików, dodaj:

```ini
[main]
LOG = 1
```

Przy `LOG = 0` komunikaty trafiają na standardowe wyjście.

CLI przyjmuje `--config /sciezka/do/verifier_cfg.ini`, a API Pythona przyjmuje
`Verifier(..., config_file="/sciezka/do/verifier_cfg.ini")`.

## Ochrona materialu TLS

Jesli w katalogu projektu znajduja sie `cert.pem` i `key.pem`, Verifier traktuje
je jako dodatkowy warunek tozsamosci dla operacji administacyjnych.

Verifier sprawdza, czy:

- oba pliki wystepuja razem
- certyfikat i klucz prywatny tworza poprawna pare
- oba pliki maja uprawnienia tylko dla wlasciciela

Operacje wrazliwe powinny zostac zablokowane, jesli ta walidacja sie nie powiedzie.

Typowe operacje administratora to:

- `--authorize`
- `--cleanup-progs`
- `--cleanup-progs-exec`

Jesli plikow nie ma, projekt moze dzialac w normalnym trybie.
Jesli jednak sa obecne, sa traktowane jako dodatkowa ochrona i musza pozostac poprawne.

Jawny dostep do plaintextu nie jest wystawiany przez komendy CLI listujace.
Hasla i sekrety sesji nalezy odczytywac tylko przez uwierzytelnione API programu po
`authenticate_and_regenerate`.

Zalecane uprawnienia:

```bash
chmod 600 cert.pem
chmod 600 key.pem
chmod 600 verifier.db verifier-db_key.key verifier-secret.key
```

## Baza i pliki kluczy

Ponizsze pliki trzeba traktowac jako jeden spojny zestaw:

- `verifier.db`
- `verifier-db_key.key`
- `verifier-secret.key`

Nie nalezy podmieniac tylko jednego z nich.

## Model dostepu

Sa dwa rozdzielone przeplywy dostepu:

- sciezka administratora: zarzadzanie programami, instancjami i uprawnieniami
- sciezka programu: uwierzytelnienie kluczem sesji i odczyt przypisanych sekretow

Te sciezki nie sa zamienne.

Wazne konsekwencje:

- podmiana `verifier-db_key.key` bez pasujacej bazy spowoduje w SQLCipher bledy typu `file is not a database`
- podmiana `verifier-secret.key` bez pasujacej bazy moze uniemozliwic odszyfrowanie zaszyfrowanych kolumn
- odtwarzanie bazy z backupu powinno zawsze przywracac tez pasujace pliki kluczy

W praktyce te trzy pliki powinny byc archiwizowane i odtwarzane razem.

## Backup i restore

Projekt zawiera pomocnicze skrypty, ktore czytaja sciezki z `verifier_cfg.ini`
lezacego obok skryptow:

- `backup_verifier_state.sh`
- `restore_verifier_state.sh`

Uzycie:

```bash
./backup_verifier_state.sh
./backup_verifier_state.sh backup
./restore_verifier_state.sh backup/verifier_state_YYYYMMDD_HHMMSS
```

Zachowanie:

- backup zawsze obejmuje caly zestaw runtime
- restore wymaga obecnosci kompletnego zestawu w katalogu backupu
- sciezki wzgledne z pliku konfiguracyjnego sa rozwiazywane wzgledem katalogu tego pliku
- odtworzone pliki sa normalizowane do uprawnien tylko dla wlasciciela

## Znacznik czasu autoryzacji

Tabela `programs` przechowuje pole `authorized_at`.

Ta wartosc sluzy do:

- pokazania, kiedy instancja programu byla ostatnio autoryzowana
- potwierdzenia, ze ponowne `--authorize` aktualizuje aktywny rekord
- ulatwienia diagnostyki i audytu

Polecenie `--create-db` powinno byc idempotentne, a jego wielokrotne uruchamianie
nie powinno psuc istniejacej bazy.

## Zarzadzanie credentialami

CLI obsluguje dwa glowne scenariusze:

- tworzenie credentiala
- linkowanie credentiala do programu i instancji

Najwazniejsze komendy:

- `--create-cred` lub `--create-cred-cmd`
- `--link-prog-cred` lub `--link-prog-cred-cmd`
- `--list-prog-creds` lub `--list-prog-creds-cmd`
- `--list-cred-progs` lub `--list-cred-progs-cmd`
- `--list-creds`
- `--add-pwd-cmd`

Credential sklada sie z:

- `context`
- `subcontext`
- zaszyfrowanego hasla

To pozwala rozrozniac np. `database/read_only` i `database/read_write`.

## Widocznosc sekretow w CLI

Domyslnie komendy typu listujacego nie powinny pokazywac odszyfrowanych sekretow.

Typowe zachowanie:

- `--list-progs` ukrywa klucz sesji (`ephemeral_password`)
- `--list-prog-creds` i `--list-prog-creds-cmd` ukrywaja hasla credentiali
- plaintext jest dostepny tylko przez uwierzytelnione API programu

To zmniejsza ryzyko przypadkowego wycieku przez:

- historie terminala
- scrollback
- zrzuty ekranu
- kopiowane logi

## Obsluga bledow

Projekt zaklada prosta, czytelna obsluge bledow:

- brak pliku konfiguracyjnego konczy inicjalizacje
- brak pliku programu oznacza, ze hash nie moze zostac policzony
- bledny `instance_key` nie zwroci rekordu z bazy
- zly stary klucz sesji uniemozliwi autoryzacje
- brak credentiala zwroci `None`

W praktyce komunikaty bledow maja od razu wskazac, czy problem dotyczy:

- konfiguracji
- pliku programu
- bazy danych
- klucza instancji
- credentiala

## Podsumowanie

Verifier umozliwia:

- zaszyfrowane przechowywanie credentiali
- przypinanie ich do konkretnego programu
- rozdzielanie instancji tego samego programu
- odswiezanie klucza po autoryzacji

To lekki, przejrzysty mechanizm do scenariuszy, w ktorych program ma sam
potwierdzic swoja tozsamosc i dopiero wtedy dostac dostep do przypisanych danych.
