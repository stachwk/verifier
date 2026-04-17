# Verifier

Verifier to mały system do przypisywania haseł i credentiali do konkretnych programów.
Program nie jest identyfikowany tylko po nazwie, ale po:

- `hash` pliku programu
- `instance_key`, czyli kluczu instancji

To oznacza, że ten sam plik może mieć kilka niezależnych instancji, a każda z nich
może mieć własne efemeryczne hasło i własne credentiale.

## Idea i sens

Verifier rozwiązuje praktyczny problem: jak przypisać sekret do konkretnego programu
w taki sposób, żeby nie wystarczyła sama nazwa pliku, katalog albo ręcznie wpisany
identyfikator.

Program najpierw udowadnia swoją tożsamość przez hash pliku. Potem udowadnia, że chodzi
o konkretną instancję, bo ten sam kod może działać w kilku środowiskach równolegle.
Dopiero wtedy może pobrać przypisany credential.

To daje trzy ważne własności:

- sekret jest przypisany do rzeczywistego pliku programu, nie do jego nazwy
- wiele instancji tego samego programu może mieć różne hasła i różne credentiale
- każda poprawna autoryzacja może odświeżyć klucz, więc poprzedni stan nie jest
  wiecznie ważny

W praktyce Verifier jest lekkim mechanizmem: program identity + instance identity +
linked secret.

## Jak to działa

1. Uruchamiasz `--create-db`, aby utworzyć tabele w bazie.
2. Uruchamiasz `--authorize`, podając nazwę programu, ścieżkę do pliku i `instance_key`.
3. CLI zapisuje:
   - hash programu w bazie
   - efemeryczne hasło dla tej instancji
   - plik `<program_name>.hash`
   - plik `<program_name>_<instance_key>.key`
4. Możesz dodać credential, np. hasło do bazy danych.
5. Następnie linkujesz credential do konkretnego programu i konkretnej instancji.
6. Program testowy uruchomiony dla tej samej instancji może:
   - odczytać poprzedni klucz z pliku
   - potwierdzić autoryzację
   - wygenerować nowe hasło i podmienić plik klucza
   - pobrać credential przypisany do tego programu

## Ważna zasada

Nie wystarczy sam hash programu.
Żeby pobrać credential, program musi być:

- autoryzowany w bazie dla konkretnego `instance_key`
- powiązany z credentialem
- uruchomiony z poprawnym plikiem klucza

## Dlaczego to jest tak zbudowane

Taki układ chroni przed kilkoma typowymi problemami:

- samą nazwę pliku da się łatwo skopiować
- sam hash nie rozróżnia środowisk uruchomieniowych
- pojedynczy wspólny sekret dla wszystkich instancji szybko przestaje być wygodny
- ręczne trzymanie haseł w plikach bez kontroli prowadzi do chaosu

Verifier daje prosty kompromis:

- baza przechowuje zaszyfrowane dane
- program ma lokalny plik klucza, który można odświeżać
- przypisanie credentiala jest jawne i zależne od konkretnej instancji

To nie jest pełny system zarządzania sekretami klasy enterprise.
To jest mały, zrozumiały mechanizm do scenariuszy, w których program sam ma
potwierdzić swoją tożsamość i dostać tylko te dane, które zostały mu przypisane.

## Jak powinien wyglądać program

Program, który korzysta z Verifiera, powinien mieć prosty układ:

1. Odczytujesz `instance_key` z argumentów wiersza poleceń.
2. Otwierasz plik `test_program_<instance_key>.key` i czytasz z niego stare hasło.
3. Tworzysz obiekt `Verifier(__file__)`, żeby program sam policzył swój hash.
4. Wywołujesz `authenticate_and_regenerate(old_pass, instance_key)`.
5. Jeśli autoryzacja się uda, możesz wywołać `get_context_password(...)`.
6. Nowe hasło zapisane przez Verifiera nadpisuje stary plik klucza.

Minimalny szkielet:

```python
from verifier import Verifier
import sys

def main():
    instance_key = sys.argv[1]
    key_file = f"test_program_{instance_key}.key"

    with open(key_file, "r") as f:
        old_pass = f.read().strip()

    verifier = Verifier(__file__)
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
- Ten sam plik, uruchomiony z innym `instance_key`, jest traktowany jako osobna instancja.
- Credentiale są zwracane dopiero po udanej autoryzacji.
- Jeśli plik programu się zmieni, hash się zmieni i istniejący rekord nie będzie pasował.

## Przykładowy przepływ

```bash
python3.12 verifier_cli.py --create-db
python3.12 verifier_cli.py --authorize test_program ./test_program.py 1
python3.12 verifier_cli.py --add-pwd-cmd ./test_program.py database read_only Secret123 1
python3.12 test_program.py 1
```

Wynik:

- program zostaje rozpoznany po hashu i `instance_key`
- stare hasło jest sprawdzane
- po udanej autoryzacji generowane jest nowe hasło
- credential `database/read_only` jest pobierany z bazy

## Główne pliki

- `verifier.py` - logika bazy, szyfrowania i autoryzacji
- `verifier_cli.py` - CLI do tworzenia bazy, autoryzacji i zarządzania credentialami
- `test_program.py` - przykładowy program testowy, który używa przypisanego klucza

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

Projekt jest udostępniony na licencji MIT. Pełny tekst znajduje się w pliku [LICENSE](/media/wojtek/virtdata/home/wojtek/git/verifier/LICENSE).

## Konfiguracja projektu

Plik `config.ini` powinien zawierać co najmniej:

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

Jesli w katalogu projektu znajduja sie `cert.pem` i `key.pem`, Verifier traktuje
je jako dodatkowy warunek tozsamosci API i sprawdza, czy para do siebie pasuje.
Baza oraz lokalne pliki kluczy sa tez normalizowane do uprawnien tylko dla wlasciciela.

## Zarządzanie credentialami

CLI obsługuje dwa główne scenariusze:

- tworzenie credentiala
- linkowanie credentiala do programu i instancji

Najważniejsze komendy:

- `--create-cred` lub `--create-cred-cmd`
- `--link-prog-cred` lub `--link-prog-cred-cmd`
- `--list-prog-creds` lub `--list-prog-creds-cmd`
- `--list-cred-progs` lub `--list-cred-progs-cmd`
- `--list-creds`
- `--add-pwd-cmd`

Credential składa się z:

- `context`
- `subcontext`
- zaszyfrowanego hasła

To pozwala rozróżniać np. `database/read_only` i `database/read_write`.

## Obsługa błędów

Projekt zakłada prostą, czytelną obsługę błędów:

- brak pliku konfiguracyjnego kończy inicjalizację
- brak pliku programu oznacza, że hash nie może zostać policzony
- błędny `instance_key` nie zwróci rekordu z bazy
- zły stary klucz uniemożliwi autoryzację
- brak credentiala zwróci `None`

W praktyce komunikaty błędów mają od razu wskazać, czy problem dotyczy:

- konfiguracji
- pliku programu
- bazy danych
- klucza instancji
- credentiala

## Podsumowanie

Verifier umożliwia:

- zaszyfrowane przechowywanie credentiali
- przypinanie ich do konkretnego programu
- rozdzielanie instancji tego samego programu
- odświeżanie klucza po autoryzacji

To lekki, przejrzysty mechanizm do scenariuszy, w których program ma sam
potwierdzić swoją tożsamość i dopiero wtedy dostać dostęp do przypisanych danych.
