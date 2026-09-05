import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-reset-password',
  imports: [CommonModule, ReactiveFormsModule, RouterLink],
  templateUrl: './reset-password.component.html',
})
export class ResetPasswordComponent implements OnInit {
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

  ngOnInit(): void {
    this.token.set(this.route.snapshot.queryParamMap.get('token') || '');
    if (!this.token()) {
      this.error.set('This reset link is missing a token. Request a new one from sign in.');
    }
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
}
