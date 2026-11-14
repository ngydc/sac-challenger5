import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/** App shell: only the router outlet, so the page (the viewer) can use the whole screen. */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {}
