# Test fixtures

Everything here is **synthetic**: no real RUG Brightspace response has been captured yet. The shapes
follow the D2L `content/toc` schema (`Modules[].Topics[]` with `TopicId`, `TypeIdentifier`, `Url`,
`Title`, `LastModifiedDate`) and the URL patterns already seen in Property Law. Neither the PIL
"smart curriculum" wrapper markup nor whether RUG's TOC fills in `LastModifiedDate` has been checked yet.

To replace them, open a signed-in Brightspace tab and save these files next to the synthetic ones,
under names without `.synthetic`. Then point the tests at the real files.
- `/d2l/api/le/1.97/564701/content/toc` (PIL) and `/d2l/api/le/1.97/564708/content/toc` (LaPoPo)
- the HTML of one PIL slide topic, the `/content/enforced/564701-…/….html` page
