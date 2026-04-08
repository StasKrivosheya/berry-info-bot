# Berry Land Query Eval Cases

Use these cases when refining `llm_prompt_guide.md` for `gpt-5.4-nano`.
Judge the routing and retrieval plan before judging the rendered answer.

## Cases

1. `які у вас є програми`
   - intent: `enumeration`
   - scope: `programs`
   - strategy: `enumeration_catalog`
   - retrieval primary: `організовані програми`
   - retrieval keywords: `організовані програми`, `види програм`

2. `що ви можете запропонувати класу`
   - intent: `overview`
   - scope: `programs`
   - strategy: `overview_summary`
   - retrieval primary: `організовані програми Berry Land`

3. `хто у вас є в зоопарку`
   - intent: `detail`
   - scope: `park_activities`
   - strategy: `detail_retrieval`
   - retrieval primary: `екскурсія на поні-ферму тварини ранчо`
   - retrieval keywords: `поні-ферма`, `тварини`, `ранчо`

4. `чи є у вас поні-ферма`
   - intent: `detail`
   - scope: `park_activities`
   - strategy: `detail_retrieval`
   - retrieval primary: `екскурсія на поні-ферму`

5. `які у вас є додаткові послуги`
   - intent: `enumeration`
   - scope: `services`
   - strategy: `enumeration_catalog`
   - retrieval primary: `додаткові послуги`

6. `скільки коштує трансфер`
   - intent: `detail`
   - scope: `transfer`
   - strategy: `detail_retrieval`
   - retrieval primary: `трансфер з Дніпра вартість`

7. `чи є де поїсти`
   - intent: `detail`
   - scope: `food`
   - strategy: `detail_retrieval`
   - retrieval primary: `кафе харчування комплексні обіди`

8. `яка різниця між Berry Bubble Boom і Пригоди на Ранчо`
   - intent: `comparison`
   - scope: `programs`
   - strategy: `comparison_summary`
   - retrieval primary: `Berry Bubble Boom Пригоди на Ранчо`
