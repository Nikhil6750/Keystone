export * from './api';
export * from './backend';
export * from './ui';

export type ComponentWithChildren<T = object> = React.FC<T & { children?: React.ReactNode }>;
