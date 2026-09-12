/**
 * The wire→domain layer.
 *
 * One module per resource, each holding the server's shape and the mapping to the app's beside each
 * other so the two cannot drift apart unnoticed. See `common.ts` for why this is explicit code
 * rather than a generic key transformer.
 */

export * from './common';
export * from './auth';
export * from './scan';
export * from './findings';
export * from './product';
export * from './report';
export * from './sahayak';
export * from './listing';
