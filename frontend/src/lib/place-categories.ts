export enum PlaceCategory {
  TouristAttraction = "tourist_attraction",
}

export const PLACE_CATEGORY_LABELS: Record<PlaceCategory, string> = {
  [PlaceCategory.TouristAttraction]: "Tourist attraction",
};

export function formatPlaceCategory(category: string): string {
  return (
    PLACE_CATEGORY_LABELS[category as PlaceCategory] ??
    category
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ")
  );
}