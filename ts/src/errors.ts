export interface DCAPIErrorPayload {
  ok?: false;
  error?: string;
  message?: string;
  [key: string]: unknown;
}

export class DCAPIError extends Error {
  readonly code: string;
  readonly payload: DCAPIErrorPayload | unknown;
  readonly response: Response;
  readonly status: number;

  constructor(params: {
    code: string;
    message: string;
    payload: DCAPIErrorPayload | unknown;
    response: Response;
    status: number;
  }) {
    super(params.message);
    this.name = "DCAPIError";
    this.code = params.code;
    this.payload = params.payload;
    this.response = params.response;
    this.status = params.status;
  }

  static fromPayload(payload: unknown, response: Response): DCAPIError {
    const record = isRecord(payload) ? payload : {};
    const code = typeof record.error === "string" ? record.error : "api_error";
    const message =
      typeof record.message === "string"
        ? record.message
        : `DC Member API request failed with HTTP ${response.status}`;

    return new DCAPIError({
      code,
      message,
      payload,
      response,
      status: response.status,
    });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
