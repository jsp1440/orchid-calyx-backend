export type Route =
  | { page: "dashboard" }
  | { page: "plants" }
  | { page: "plant"; plantId: string }
  | { page: "add" }
  | { page: "search" }
  | { page: "scan" }
  | { page: "deferred"; feature: string }
  | { page: "not-found" };

export function parseRoute(pathname: string): Route {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/" || path === "/conservatory") return { page: "dashboard" };
  if (path === "/conservatory/plants") return { page: "plants" };
  if (path === "/conservatory/plants/new") return { page: "add" };
  if (path === "/conservatory/search") return { page: "search" };
  if (path === "/conservatory/scan") return { page: "scan" };
  const plant = path.match(/^\/conservatory\/plants\/([^/]+)$/);
  if (plant) return { page: "plant", plantId: decodeURIComponent(plant[1]) };
  const deferred = path.match(/^\/conservatory\/(reports|environment|blooms|repotting|reminders|media|exports|sharing)$/);
  if (deferred) return { page: "deferred", feature: deferred[1] };
  return { page: "not-found" };
}

export function navigate(path: string): void {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
