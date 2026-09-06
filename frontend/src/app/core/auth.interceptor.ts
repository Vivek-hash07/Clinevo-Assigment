import { HttpInterceptorFn } from '@angular/common/http';

import { environment } from './environment';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const api = environment.apiUrl.replace(/\/$/, '');
  const toApi = api ? req.url.startsWith(api) : req.url.includes('/api/');
  if (toApi) {
    return next(req.clone({ withCredentials: true }));
  }
  return next(req);
};
