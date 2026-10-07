import type {Page} from '@playwright/test';
import {mock as centralMock} from './settings-mocks';
export const mock=(page:Page,configured=true)=>centralMock(page,configured,'http://127.0.0.1:15274');
