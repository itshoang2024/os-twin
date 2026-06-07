
import { expect } from 'chai';
import sinon from 'sinon';
import { SlackConnector } from '../src/connectors/slack';
import api from '../src/api';
import * as sessions from '../src/sessions';

describe('SlackConnector Integration', () => {
  let connector: SlackConnector;
  let sandbox: sinon.SinonSandbox;

  beforeEach(async () => {
    sandbox = sinon.createSandbox();
    connector = new SlackConnector();
    // Mock the Bolt App
    (connector as any).app = {
      command: sinon.stub(),
      action: sinon.stub(),
      message: sinon.stub(),
      use: sinon.stub(),
      start: sinon.stub().resolves(),
      stop: sinon.stub().resolves(),
    };
    connector.status = 'connected';
  });

  afterEach(() => {
    sandbox.restore();
  });

  it('isAuthorized returns false if no users are explicitly paired', () => {
    expect((connector as any).isAuthorized('u1')).to.be.false;
  });

  it('isAuthorized returns true if user is in authorized list', () => {
    (connector as any).authorizedUsers = new Set(['u1']);
    expect((connector as any).isAuthorized('u1')).to.be.true;
    expect((connector as any).isAuthorized('u2')).to.be.false;
  });

  describe('formatMrkdwn', () => {
    it('converts bold and links', () => {
      const input = 'Check **this** [link](http://x.com)';
      const output = (connector as any).formatMrkdwn(input);
      expect(output).to.equal('Check *this* <http://x.com|link>');
    });
  });

  it('translateResponse handles buttons', () => {
    const resp = {
      text: 'hi',
      buttons: [[{ label: 'Go', callbackData: 'cmd:go' }]]
    };
    const output = (connector as any).translateResponse(resp);
    expect(output.blocks).to.have.lengthOf(2);
    expect(output.blocks[1].type).to.equal('actions');
    expect(output.blocks[1].elements[0].text.text).to.equal('Go');
  });
});
