# AGENTS.md
Zawsze najpierw użyj serwera MCP MemPalace do sprawdzenia pamieci projektu, poprzednich decyzji, rozmow i kontekstu miedzy projektami, chyba ze wyraznie napisze inaczej.
Zanim odpowiesz lub zaczniesz modyfikowac kod, najpierw sprawdz MemPalace i wykorzystaj pamiec projektu, wczesniejsze decyzje oraz powiazany kontekst.

## Cel
Ten plik definiuje zasady pracy agenta w tym repozytorium.

## Założenia bezpieczeństwa
- Źródłem prawdy jest warstwa API w `Verifier` i `verifier_cli.py`, a nie bezpośredni odczyt pliku bazy.
- Operacje na danych mają przechodzić przez jawne metody API, nie przez otwieranie pliku bazy z zewnątrz.
- Jeśli dostępne są `cert.pem` i `key.pem`, traktujemy je jako dodatkowy warunek wejścia do operacji wrażliwych i weryfikujemy, że para do siebie pasuje.
- Dodanie programu (`--authorize`) jest dozwolone tylko dla administratora potwierdzonego poprawną parą `cert.pem` i `key.pem`.
- Pliki bazy, kluczy i sekretów muszą mieć obostrzone uprawnienia, co najmniej ograniczone do właściciela procesu.
- Nie wprowadzamy ścieżek, które omijają API i czytają lub modyfikują zawartość bazy bezpośrednio.
- Program pobiera dane na podstawie hash'a programu, `INSTANCE_KEY` i aktywnego hasła sesji.
- Hasło sesji jest generowane ponownie po każdej autoryzacji programu.

## Komunikacja
- Domyślny jezyk projektu to angielski ale zrob tłumacznie dla jezyka polskiego, 
- Rob opisy zwięźle i rzeczowo.
- Najpierw podawaj wynik, potem krotki kontekst.
- Nie uzywaj ozdobnikow ani dlugich wstepow.

## Commity
- Format commit message: tylko numeracja.
- Wzor: `VR 1.XX.XXX`
- Nie dodawaj opisu po numerze.
- Kolejny numer zwiekszaj sekwencyjnie wzgledem ostatniego commita.
