export function visibleItems(items, expanded, collapsedCount = 4) {
  if (!Array.isArray(items)) return [];
  if (!Number.isInteger(collapsedCount) || collapsedCount < 1) {
    throw new Error("DISCLOSURE_COUNT_INVALID");
  }
  return expanded ? [...items] : items.slice(0, collapsedCount);
}

export function createDisclosure({ itemCount, collapsedCount = 4 }) {
  if (
    !Number.isInteger(itemCount)
    || itemCount < 0
    || !Number.isInteger(collapsedCount)
    || collapsedCount < 1
  ) {
    throw new Error("DISCLOSURE_INVALID");
  }
  let expanded = false;
  return {
    get expanded() { return expanded; },
    get totalCount() { return itemCount; },
    expand() { expanded = true; },
    collapse() { expanded = false; },
    toggle() { expanded = !expanded; },
    visibleIndexes() {
      const count = expanded ? itemCount : Math.min(itemCount, collapsedCount);
      return Array.from({ length: count }, (_value, index) => index);
    },
  };
}
