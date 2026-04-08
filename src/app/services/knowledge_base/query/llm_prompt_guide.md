# Berry Land Query Routing Guide

Classify Ukrainian Berry Land KB queries and return only schema fields.
Do not answer the user.

## Labels

- `intent=detail`: asks for one fact, condition, item, schedule, price, or availability.
- `intent=enumeration`: asks for a list of options, names, or types.
- `intent=overview`: asks broadly what Berry Land offers.
- `intent=comparison`: compares named options.
- `intent=unknown`: use only when evidence is genuinely weak.

- `scope=programs`: organized programs, excursions, camps, graduation programs, team building.
- `scope=services`: extra services, gazebos, insurance, gifts, operations.
- `scope=park_activities`: attractions, leisure, pool, playground, pony-farm excursions, water fun.
- `scope=food`: meals, cafe, treats, lunches.
- `scope=zones`: ranch, farm, greenhouse, camping, named park zones.
- `scope=pricing`: tickets, prices, discounts.
- `scope=transfer`: transfer, buses, transport.
- `scope=general`: only when no narrower scope fits.

- `strategy=detail_retrieval`: narrow fact lookup with retrieval.
- `strategy=enumeration_catalog`: structure-first list answer.
- `strategy=overview_summary`: structure-first grouped summary.
- `strategy=comparison_summary`: compare candidates with retrieval support.
- `strategy=safe_fallback`: only when evidence is weak.

## Retrieval hints

- Use short Berry Land phrases, not sentences.
- Prefer canonical KB wording over user slang.
- If the user says `зоопарк`, map toward Berry Land farm wording such as `поні-ферма`, `тварини`, `ранчо`, `ферма`.
- Avoid `unknown`, `general`, and `safe_fallback` when a plausible Berry Land mapping exists.
- In normal fallback, one strong rewrite is better than many variants.

## Canonical KB phrases

- `організовані програми`
- `екскурсія на поні-ферму`
- `ферма до тваринок`
- `Пригоди на Ранчо`
- `додаткові послуги`
- `трансфер з Дніпра`
- `комплексні обіди`
- `альтанка з мангалом`

## Examples

1. Query: `які у вас є програми`
   Intent: `enumeration`
   Scope: `programs`
   Strategy: `enumeration_catalog`
   Retrieval primary: `організовані програми`
   Retrieval keywords: `організовані програми`

2. Query: `що ви можете запропонувати класу`
   Intent: `overview`
   Scope: `programs`
   Strategy: `overview_summary`
   Retrieval primary: `організовані програми Berry Land`
   Retrieval keywords: `організовані програми`, `екскурсія`

3. Query: `хто у вас є в зоопарку`
   Intent: `detail`
   Scope: `park_activities`
   Strategy: `detail_retrieval`
   Retrieval primary: `екскурсія на поні-ферму тварини ранчо`
   Retrieval keywords: `поні-ферма`, `тварини`, `ранчо`

4. Query: `скільки коштує трансфер`
   Intent: `detail`
   Scope: `transfer`
   Strategy: `detail_retrieval`
   Retrieval primary: `трансфер з Дніпра вартість`
   Retrieval keywords: `трансфер`, `вартість`

5. Query: `чи є де поїсти`
   Intent: `detail`
   Scope: `food`
   Strategy: `detail_retrieval`
   Retrieval primary: `кафе харчування комплексні обіди`
   Retrieval keywords: `кафе`, `харчування`, `комплексні обіди`
