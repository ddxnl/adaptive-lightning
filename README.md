# Adaptive Lightning

Integracja do Home Assistanta, która automatycznie ustawia **jasność i temperaturę barwową** wybranych świateł na podstawie położenia słońca (`sun.sun`: wysokość i azymut), pory dnia i – opcjonalnie – pogody. Nigdy nie ustawia kolorów.

Po wybraniu świateł działa sama: gdy światło zostanie włączone przez cokolwiek (aplikacja, automatyzacja, fizyczny przycisk, pilot Zigbee), dostaje wartości odpowiednie na daną chwilę. Włączone światła są potem płynnie korygowane.

## Instalacja

1. Skopiuj katalog `custom_components/adaptive_lightning` do `config/custom_components/` w Home Assistancie (albo dodaj to repozytorium w HACS jako własne repozytorium typu „Integration”).
2. Zrestartuj Home Assistanta.
3. Ustawienia → Urządzenia i usługi → Dodaj integrację → **Adaptive Lightning**, wybierz światła.

Można dodać kilka wpisów, np. osobne profile dla różnych pokoi.

## Jak wyliczane są wartości

| Czynnik | Wpływ |
|---|---|
| Wysokość słońca | Główny czynnik. Od zmierzchu cywilnego (−6°) do „pełnego dnia” barwa przechodzi od najcieplejszej do najzimniejszej, a jasność od wieczornej do dziennej. Próg „pełnego dnia” zależy od dzisiejszej wysokości słońca w południe, więc niskie zimowe słońce też daje pełną dzienną barwę. |
| Azymut słońca | Gdy słońce jest po zachodniej stronie nieba, światło jest cieplejsze niż przy tej samej wysokości rano (domyślnie do 15%). |
| Pora dnia | Od 21:00 światło stopniowo ciemnieje i ociepla się, o 23:00 osiąga poziom nocny, który trwa do 06:00; potem 30 minut rozjaśniania. Po zachodzie słońca, ale przed 21:00, jasność zostaje na poziomie wieczornym (zimą nie robi się ciemno o 16:00). |
| Pogoda (opcjonalnie) | W pochmurny dzień światło jest nieco cieplejsze i jaśniejsze. Domyślnie wyłączone – włącza się w opcjach razem z wyborem encji `weather`. |

Wszystkie progi, godziny i zakresy zmienia się w opcjach integracji (**Konfiguruj**).

## Możliwości urządzeń

- Światło z regulacją temperatury barwowej: wartość jest przycinana do zakresu, który to konkretne światło zgłasza (`min_color_temp_kelvin` / `max_color_temp_kelvin`).
- Światło tylko ściemnialne albo tylko kolorowe (bez trybu temperatury barwowej): ustawiana jest sama jasność.
- Światło tylko wł./wył.: pomijane.
- Czas przejścia jest wysyłany tylko do świateł, które go obsługują.

## Ręczne sterowanie i sceny

- `light.turn_on` z jawnie podaną jasnością lub barwą (np. scena) jest respektowane – integracja uzupełnia tylko parametr, którego nie podano.
- Jeśli ręcznie zmienisz jasność lub barwę świecącego światła, ten parametr przestaje być korygowany do czasu wyłączenia i ponownego włączenia światła.
- Każdy wpis ma przełącznik **Adaptacja** (całkowite wyłączenie; w atrybutach widać światła sterowane ręcznie) oraz dwa sensory z aktualnie wyliczoną temperaturą barwową i jasnością.

## Ograniczenia

- Wartości są ustawiane tuż **po** włączeniu, więc światło może na ułamek sekundy zaświecić poprzednimi ustawieniami.
- Wymagana jest encja `sun.sun` (integracja „Słońce”, domyślnie włączona).

## Testy

```
pip install pytest-homeassistant-custom-component
pytest
```

`tests/test_calc.py` testuje sam algorytm i nie wymaga Home Assistanta.
