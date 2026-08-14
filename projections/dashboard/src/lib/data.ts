import type { Dataset } from "./types";

const DATA_URL = "/data/players_2026_27.json";

/** Thrown when the dataset can't be fetched or parsed, so callers can render
 * a "run the pipeline first" empty state instead of a generic error. */
export class DataUnavailableError extends Error {
  readonly cause?: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.name = "DataUnavailableError";
    this.cause = cause;
  }
}

/** Fetches and types the pipeline's exported dataset from the public dir. */
export async function loadPlayers(): Promise<Dataset> {
  let response: Response;
  try {
    response = await fetch(DATA_URL);
  } catch (err) {
    throw new DataUnavailableError("Failed to reach the projections dataset.", err);
  }

  if (!response.ok) {
    throw new DataUnavailableError(
      `Dataset not found at ${DATA_URL} (status ${response.status}). Run the projections pipeline first.`,
    );
  }

  try {
    return (await response.json()) as Dataset;
  } catch (err) {
    throw new DataUnavailableError("Dataset response was not valid JSON.", err);
  }
}
