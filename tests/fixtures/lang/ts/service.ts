/**
 * Service layer.
 */
import { Injectable } from './di';

export const MAX_RETRIES = 3;
const internalCache = new Map<string, number>();

export type Id = string | number;

export interface Repo<T> {
  find(id: Id): Promise<T>;
  readonly name: string;
}

export enum Level { Low, High = 'high' }

@Injectable({ scope: 'app' })
export class UserService<T extends { id: Id }> implements Repo<T> {
  readonly name = 'users';
  #secret = `tpl ${`nested ${1 + 1}`} }`;
  private cache: Record<string, T> = {};
  static count = 0;

  constructor(private readonly repo: Repo<T>) {}

  async find(id: Id): Promise<T> {
    const re = /[{}]+/g;
    return this.repo.find(id);
  }

  get size(): number { return 0; }

  handler = (e: Event): void => {
    console.log('}');
  };

  private helper(): void {}
}

export function overload(a: string): string;
export function overload(a: number): number;
export function overload(a: any): any {
  return a;
}

export const arrow = async (x: number): Promise<number> => {
  return x * 2;
};

export default function main() {
  return 0;
}

declare module 'foo' {
  export function bar(): void;
}

export namespace Utils {
  export function clamp(x: number) { return x; }
}
