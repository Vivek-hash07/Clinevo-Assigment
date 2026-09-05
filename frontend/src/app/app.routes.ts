import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/auth.guard';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'inbox' },
  {
    path: 'sign-in',
    canActivate: [guestGuard],
    loadComponent: () => import('./pages/sign-in/sign-in.component').then((m) => m.SignInComponent),
  },
  {
    path: 'sign-up',
    canActivate: [guestGuard],
    loadComponent: () => import('./pages/sign-up/sign-up.component').then((m) => m.SignUpComponent),
  },
  {
    path: 'forgot-password',
    canActivate: [guestGuard],
    loadComponent: () =>
      import('./pages/forgot-password/forgot-password.component').then((m) => m.ForgotPasswordComponent),
  },
  {
    path: 'reset-password',
    loadComponent: () =>
      import('./pages/reset-password/reset-password.component').then((m) => m.ResetPasswordComponent),
  },
  {
    path: 'inbox',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/inbox/inbox.component').then((m) => m.InboxComponent),
  },
  { path: '**', redirectTo: 'inbox' },
];
