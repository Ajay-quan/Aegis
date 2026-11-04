// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 AegisTrace contributors
export class AegisError extends Error {
  constructor(public readonly status: number, public readonly code: string, message: string) {
    super(`${status} ${code}: ${message}`);
    this.name = new.target.name;
  }
}
export class AuthenticationError extends AegisError {}
export class PermissionDeniedError extends AegisError {}
export class NotFoundError extends AegisError {}
export class ConflictError extends AegisError {}
export class ValidationError extends AegisError {}
export class RateLimitedError extends AegisError {}
export class ServiceUnavailableError extends AegisError {}

const BY_STATUS: Record<number, typeof AegisError> = {
  401: AuthenticationError, 403: PermissionDeniedError, 404: NotFoundError, 409: ConflictError,
  422: ValidationError, 429: RateLimitedError, 503: ServiceUnavailableError,
};

export function errorFromResponse(status: number, body: unknown): AegisError {
  const err = (typeof body === "object" && body !== null && "error" in body
    ? (body as { error: { code?: string; message?: string } }).error : {}) ?? {};
  const Cls = BY_STATUS[status] ?? AegisError;
  return new Cls(status, err.code ?? "error", err.message ?? "request failed");
}
