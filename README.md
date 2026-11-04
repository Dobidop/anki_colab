# LiU-kort: Anki-lekar för Grundlärarprogrammet F-3

Gemensamma Anki-kort för Grundlärarprogrammet F-3 (L1GF3) vid Linköpings
universitet, Campus Linköping, med start HT 2026. Korten skrivs som vanliga
textfiler här och byggs automatiskt till en Anki-lek varje gång något ändras.

## Ladda ner och importera

1. Hämta **[liu-kort.apkg](../../releases/latest/download/liu-kort.apkg)**
   (alltid den senaste versionen, se även [alla versioner](../../releases)).
2. Öppna Anki på datorn: **Arkiv → Importera** och välj filen. Behåll
   standardvalen i importdialogen.
3. Repetera föräldraleken **LiU**, så blandas kurserna. Det är det som håller
   972G01 vid liv medan du läser 972G03.

Synka sedan till AnkiWeb som vanligt för att få korten i mobilen. AnkiDroid
och AnkiMobile kan också importera `.apkg` direkt.

### Uppdatera

Ladda ner den nya filen och importera den på samma sätt. Ändrade kort
uppdateras och nya kort läggs till, och din repetitionshistorik finns kvar.

> [!important] Ändra inte korten i Anki
> Vid nästa import skrivs ett kort tillbaka till det som står här, och ändringar
> du gjort i Anki försvinner. Har du hittat ett fel, rapportera det i stället (se
> nedan) så blir det rätt för alla. Taggar, flaggor och att stänga av (suspend)
> ett kort påverkas inte.

## Vad som finns i leken

| Lek | Innehåll |
|---|---|
| `LiU::972G01` | Allmändidaktik: Edling, Thorsten & Samuelsson, Lindqvist och referensteknik |
| `LiU::972G03::Begreppslista` | Kursens begreppslista svenska–engelska, med definitioner ur McMillans ordlista |
| `LiU::972G03::Föreläsningar` | Begrepp ur de inspelade föreläsningarna |
| `LiU::972G03::Litteratur` | Kort ur kurslitteraturen |
| `LiU::972G17::Begreppslista` | Studiehandledningens begreppslista |
| `LiU::972G17::Luiselli` | Luiselli m.fl. (2005), artikeluppgiften |

Begreppslekarna har en undermapp **Framåt** (begrepp → definition) och
**Omvänt** (definition → begrepp), så du kan öva en riktning i taget.

Varje kort visar sin källa med sidnummer och den fullständiga referensen i
APA 7. Längst ner står kortets fil och id, med en länk för att rapportera fel.

### ⚠ = inte kontrollerat mot kursmaterialet

En del baksidor är skrivna med AI-hjälp. Där uppgiften inte står i
kursmaterialet utan är skriven ur allmän kunskap är kortet märkt **⚠** och har
taggen `okontrollerad`. Sök på `tag:okontrollerad` i Anki för att se dem, eller
stäng av dem om du bara vill ha det som står i böckerna. Kontrollerar du ett
sådant kort mot boken, berätta det så tas ⚠ bort.

### Frågor utan svar

Många frågor saknar ännu baksida, framför allt till Woolfolk och kursböckerna
i 972G01. De finns i filerna men kommer inte med i leken förrän någon har
skrivit ett svar. Det är det bästa stället att börja bidra. Det är också det
bästa sättet att lära sig: ett svar du formulerat själv sitter bättre än ett du
läst.

## Bidra

Två sätt, båda lika välkomna:

**1. Skapa ett issue** (inget kunnande om git behövs, bara ett GitHub-konto).
Gå till [Issues → New issue](../../issues/new/choose) och välj

- **Nytt kort** för ett nytt kort eller ett svar på en fråga utan baksida
- **Fel i kort** när något är fel. Länken *rapportera fel* på kortet i Anki
  fyller i vilket kort det gäller.

**2. Gör en pull request.** Redigera filen direkt på GitHub (pennan uppe till
höger) eller i en egen klon. En automatisk kontroll körs på varje pull request,
och när den slås ihop byggs en ny version av leken.

Har du inget GitHub-konto, skicka förslaget till den som håller i leken.

### Hur ett kort ser ut

Korten ligger i en mapp per kurskod, en fil per bok, artikel eller begreppslista:

```markdown
### Vad är formativ bedömning?
<!-- anki: 90601bdb -->
> källa: McMillan (2018), s. 516 · lärandemål: använda bedömningsteoretiska begrepp …

**Svar:** Bedömning under lärandet, för att ge återkoppling och anpassa
undervisningen medan det fortfarande går att påverka.
```

- **`###` är frågan.** Allt under `**Svar:**` fram till nästa rubrik eller `---`
  är baksidan.
- **`> källa:`** med sidnummer, eller tidsstämpel för en inspelad föreläsning.
  Lägg gärna till vilket lärandemål kortet hör till.
- **`<!-- anki: … -->`** är kortets id. Skriv inte dit något själv: nya kort får
  ett id automatiskt när ändringen slås ihop. Rör aldrig ett befintligt id och
  kopiera det inte när du kopierar ett kort. Ett nytt id gör kortet till ett nytt
  kort för alla, och repetitionshistoriken går förlorad.
- **Ett kort, en sak.** Blir baksidan längre än fem rader är det två kort.
- **Svenska termer.** Examinationen sker på svenska. Den engelska termen kan stå
  inom parentes först på baksidan, som i begreppslistorna.
- **Märk med ⚠** det som inte står i kursmaterialet.
- **Inga längre citat.** Kurslitteraturen är upphovsrättsskyddad. Skriv med egna
  ord och hänvisa till sidan.

### En ny fil

Börja med frontmatter. `references:` är källornas fullständiga referenser i
APA 7 och visas på varje kort i filen.

```yaml
---
title: Kort — Carr (2008)
course: 972G03
type: cards
deck: Litteratur
references:
  - "Carr, S. C. (2008). Student and peer evaluation: Feedback for all learners. *Teaching Exceptional Children, 40*, 24–30."
tags: [bedomning, kamratbedomning]
---
```

`deck:` lägger korten i en underlek (`LiU::972G03::Litteratur`).
`reverse: true` ger varje "Vad är X?"-kort en omvänd variant, och passar bara
för begreppslistor. Filnamnet följer `författare-år.md` med bara a–z, så `å`,
`ä` och `ö` blir `a`, `a` och `o`.

## Teknik

`tools/build.py` läser filerna och bygger `dist/liu-kort.apkg` med
[genanki](https://github.com/kerrickstaley/genanki). GitHub Action-flödet
[`build.yml`](.github/workflows/build.yml) kontrollerar varje pull request. Vid
varje ändring på `main` delar det ut id till nya kort, bygger leken och
publicerar den som en ny release.

```bash
pip install -r requirements.txt
python tools/build.py --check        # kontrollera utan att bygga
python tools/build.py                # bygg dist/liu-kort.apkg
```

Det id som står i en fil blir kortets GUID i Anki. Det är därför en ny import
uppdaterar ett kort i stället för att lägga till en kopia.
