# S-4: Brave Search API, links only (field names and counts only)

- request parameters: ['count', 'extra_snippets', 'q', 'result_filter', 'search_lang', 'summary'] with {'extra_snippets': 'false', 'summary': 'false', 'result_filter': 'web'}
- top-level response fields: ['mixed', 'query', 'type', 'web']
- `web` fields: ['family_friendly', 'results', 'type']
- web results: 10; fields per result: ['age', 'article', 'content_type', 'description', 'family_friendly', 'is_live', 'is_source_both', 'is_source_local', 'language', 'meta_url', 'page_age', 'profile', 'subtype', 'thumbnail', 'title', 'type', 'url']
- content fields present (should be none): none
- rate-limit headers: {'x-ratelimit-limit': '50, 0', 'x-ratelimit-policy': '50;w=1, 0;w=2678400', 'x-ratelimit-remaining': '49, 0', 'x-ratelimit-reset': '1, 2466201'}
- adapter hits: 10; fields: ['rank', 'snippet', 'title', 'url']
- cost: 2 requests on the Search plan (about $0.01, inside the monthly free credit)
- `article` holds author, date and publisher only (no page text); `profile`, `meta_url` and
  `thumbnail` are site metadata; `description` is the search snippet (79-523 characters),
  which the adapter keeps as `snippet` and the workflow never uses as evidence (AT-06)
- rate limit: 50 requests per second, no monthly quota on this plan (`0;w=2678400`); the
  configured `search.rate_per_s: 1` is far inside it
- verdict: links only confirmed; the recorded response in `tests/fixtures/search/` keeps
  Brave's field layout with fictional values
