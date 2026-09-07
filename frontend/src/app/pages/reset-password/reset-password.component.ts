import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { Subscription, combineLatest } from 'rxjs';

import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-reset-password',
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './reset-password.component.html',
})
export class ResetPasswordComponent implements OnInit, OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly submitting = signal(false);
  readonly error = signal('');
  readonly token = signal('');

  readonly form = this.fb.nonNullable.group({
    password: ['', [Validators.required, Validators.minLength(8)]],
    confirm: ['', [Validators.required]],
  });

  private routeSub?: Subscription;

  ngOnInit(): void {
    this.routeSub = combineLatest([this.route.paramMap, this.route.queryParamMap]).subscribe(
      ([params, query]) => {
        const token = this.cleanToken(params.get('token') || query.get('token') || '');
        this.token.set(token);
        if (!token && !this.error()) {
          this.error.set('This reset link is missing a token. Request a new one from sign in.');
        }
      },
    );
  }

  ngOnDestroy(): void {
    this.routeSub?.unsubscribe();
  }

  submit(): void {
    if (!this.token() || this.submitting()) {
      return;
    }
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const { password, confirm } = this.form.getRawValue();
    if (password !== confirm) {
      this.error.set('Passwords do not match.');
      return;
    }
    this.submitting.set(true);
    this.error.set('');
    this.auth.resetPassword(this.token(), password).subscribe({
      next: () => void this.router.navigateByUrl('/inbox'),
      error: (err: HttpErrorResponse) => {
        this.submitting.set(false);
        if (err.status === 0) {
          this.error.set('The server could not be reached. Check your connection and try again.');
          return;
        }
        const detail = err.error?.detail;
        this.error.set(
          typeof detail === 'string'
            ? detail
            : 'The password could not be changed. Request a new reset link and try again.',
        );
      },
    });
  }

  private cleanToken(raw: string): string {
    let token = (raw || '').trim().replace(/^<|>$/g, '');
    try {
      token = decodeURIComponent(token);
    } catch {
      // Already decoded, or the value is not a valid escape sequence.
    }
    return token.replace(/\s+/g, '');
  }
}
