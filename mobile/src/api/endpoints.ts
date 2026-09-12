/**
 * One typed function per endpoint in docs/02-trd.md §5.
 *
 * This is the only place that knows a path string. Hooks call these, screens call hooks, and
 * nothing anywhere composes a URL by hand.
 */

import { transport } from './transport';
import type {
  BisApplicabilityBody,
  BisApplicabilityResponse,
  ConfirmFieldsBody,
  ConfirmFieldsResponse,
  CreateReportBody,
  CreateReportResponse,
  CreateScanBody,
  CreateScanResponse,
  GetFindingsResponse,
  GetReportResponse,
  GetScanResponse,
  ListProductsQuery,
  ListProductsResponse,
  ListScansQuery,
  ListScansResponse,
  OtpRequestBody,
  OtpRequestResponse,
  OtpVerifyBody,
  OtpVerifyResponse,
  SahayakAskBody,
  SahayakAskResponse,
  SubmitScanResponse,
} from './types';

export const api = {
  requestOtp: (body: OtpRequestBody) =>
    transport.request<OtpRequestResponse>({ method: 'POST', path: '/auth/otp/request', body }),

  verifyOtp: (body: OtpVerifyBody) =>
    transport.request<OtpVerifyResponse>({ method: 'POST', path: '/auth/otp/verify', body }),

  listProducts: (query: ListProductsQuery = {}) =>
    transport.request<ListProductsResponse>({ method: 'GET', path: '/products', query }),

  listScans: (query: ListScansQuery = {}) =>
    transport.request<ListScansResponse>({ method: 'GET', path: '/scans', query }),

  getScan: (scanId: string) =>
    transport.request<GetScanResponse>({ method: 'GET', path: `/scans/${scanId}` }),

  getFindings: (scanId: string) =>
    transport.request<GetFindingsResponse>({ method: 'GET', path: `/scans/${scanId}/findings` }),

  createScan: (body: CreateScanBody, idempotencyKey: string) =>
    transport.request<CreateScanResponse>({
      method: 'POST',
      path: '/scans',
      body,
      idempotencyKey,
    }),

  submitScan: (scanId: string) =>
    transport.request<SubmitScanResponse>({ method: 'POST', path: `/scans/${scanId}/submit` }),

  confirmFields: (scanId: string, body: ConfirmFieldsBody) =>
    transport.request<ConfirmFieldsResponse>({
      method: 'POST',
      path: `/scans/${scanId}/confirm-fields`,
      body,
    }),

  createReport: (scanId: string, body: CreateReportBody) =>
    transport.request<CreateReportResponse>({
      method: 'POST',
      path: `/scans/${scanId}/report`,
      body,
    }),

  getReport: (reportId: string) =>
    transport.request<GetReportResponse>({ method: 'GET', path: `/reports/${reportId}` }),

  askSahayak: (body: SahayakAskBody) =>
    transport.request<SahayakAskResponse>({ method: 'POST', path: '/sahayak/ask', body }),

  bisApplicability: (body: BisApplicabilityBody) =>
    transport.request<BisApplicabilityResponse>({
      method: 'POST',
      path: '/bis/applicability',
      body,
    }),
} as const;
