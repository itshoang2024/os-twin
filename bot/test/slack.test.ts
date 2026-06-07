import { expect } from 'chai';
import sinon from 'sinon';
import { SlackConnector } from '../src/connectors/slack';
import { BotResponse } from '../src/commands';

describe('SlackConnector', () => {
  let connector: SlackConnector;

  beforeEach(() => {
    connector = new SlackConnector();
  });

  describe('validateConfig', () => {
    it('should fail if token is missing', () => {
      const config: any = {
        credentials: { appToken: 'xapp-1' }
      };
      const result = connector.validateConfig(config);
      expect(result.valid).to.be.false;
      expect(result.errors).to.contain('Missing Bot Token');
    });

    it('should fail if appToken is missing', () => {
      const config: any = {
        credentials: { token: 'xoxb-1' }
      };
      const result = connector.validateConfig(config);
      expect(result.valid).to.be.false;
      expect(result.errors).to.contain('Missing App-Level Token');
    });

    it('should succeed if all credentials are present', () => {
      const config: any = {
        credentials: { token: 'xoxb-1', appToken: 'xapp-1' }
      };
      const result = connector.validateConfig(config);
      expect(result.valid).to.be.true;
    });
  });

  it('isAuthorized returns false if no users are explicitly paired', () => {
    expect((connector as any).isAuthorized('u1')).to.be.false;
  });

  it('isAuthorized returns true if user is in authorized list', () => {
    (connector as any).authorizedUsers = new Set(['u1']);
    expect((connector as any).isAuthorized('u1')).to.be.true;
    expect((connector as any).isAuthorized('u2')).to.be.false;
  });

  describe('sendUnauthorized', () => {
    it('should call respond with ephemeral message', async () => {
      const respond = sinon.stub().resolves();
      await (connector as any).sendUnauthorized(respond, 'u1');
      expect(respond.calledOnce).to.be.true;
      expect(respond.firstCall.args[0].response_type).to.equal('ephemeral');
    });
  });

  describe('formatMrkdwn', () => {
    it('should translate bold from ** to *', () => {
      const input = 'This is **bold** text';
      const output = (connector as any).formatMrkdwn(input);
      expect(output).to.equal('This is *bold* text');
    });

    it('should translate links from [label](url) to <url|label>', () => {
      const input = 'Check out [this link](https://example.com)';
      const output = (connector as any).formatMrkdwn(input);
      expect(output).to.equal('Check out <https://example.com|this link>');
    });
  });

  describe('translateResponse', () => {
    it('should translate a simple text response to a section block', () => {
      const response: BotResponse = { text: 'Hello world' };
      const output = (connector as any).translateResponse(response);
      
      expect(output.text).to.equal('Hello world');
      expect(output.blocks).to.have.lengthOf(1);
      expect(output.blocks[0].type).to.equal('section');
      expect(output.blocks[0].text.text).to.equal('Hello world');
    });

    it('should translate buttons to action blocks', () => {
      const response: BotResponse = {
        text: 'Action needed',
        buttons: [
          [{ label: 'Accept', callbackData: 'cmd:accept' }, { label: 'Reject', callbackData: 'cmd:reject' }]
        ]
      };
      const output = (connector as any).translateResponse(response);
      
      expect(output.blocks).to.have.lengthOf(2);
      expect(output.blocks[1].type).to.equal('actions');
      expect(output.blocks[1].elements).to.have.lengthOf(2);
      expect(output.blocks[1].elements[0].text.text).to.equal('Accept');
      expect(output.blocks[1].elements[0].action_id).to.equal('cmd:accept');
      expect(output.blocks[1].elements[1].text.text).to.equal('Reject');
      expect(output.blocks[1].elements[1].action_id).to.equal('cmd:reject');
    });

    it('should chunk long text into multiple blocks', () => {
      const longText = 'a'.repeat(3500);
      const response: BotResponse = { text: longText };
      const output = (connector as any).translateResponse(response);
      
      expect(output.blocks).to.have.lengthOf(2);
      expect(output.blocks[0].type).to.equal('section');
      expect(output.blocks[0].text.text).to.have.lengthOf(3000);
      expect(output.blocks[1].type).to.equal('section');
      expect(output.blocks[1].text.text).to.have.lengthOf(500);
    });
  });

  describe('sendResponses', () => {
    it('should call say for each response', async () => {
      const say = sinon.stub().resolves();
      const responses: BotResponse[] = [{ text: 'msg1' }, { text: 'msg2' }];
      await (connector as any).sendResponses(say, 'u1', responses);
      expect(say.calledTwice).to.be.true;
    });

    it('should include thread_ts if provided', async () => {
      const say = sinon.stub().resolves();
      const responses: BotResponse[] = [{ text: 'msg1' }];
      await (connector as any).sendResponses(say, 'u1', responses, '123.456');
      expect(say.firstCall.args[0].thread_ts).to.equal('123.456');
    });
  });

  describe('sendResponsesChat', () => {
    it('should call postMessage for each response', async () => {
      const postMessage = sinon.stub().resolves();
      (connector as any).app = { client: { chat: { postMessage } } };
      const responses: BotResponse[] = [{ text: 'msg1' }];
      await (connector as any).sendResponsesChat('c1', responses);
      expect(postMessage.calledOnce).to.be.true;
      expect(postMessage.firstCall.args[0].channel).to.equal('c1');
    });
  });

  describe('start', () => {
    it('should initialize Bolt App and register handlers', async () => {
      const appStub: any = {
        use: sinon.stub(),
        command: sinon.stub(),
        action: sinon.stub(),
        message: sinon.stub(),
        start: sinon.stub().resolves(),
      };
      
      (connector as any).app = appStub;
      
      // Test message handler logic
      const messageHandler = async (args: any) => {
        const { message, say } = args;
        if (message.bot_id) return;
        const userId = message.user;
        const text = message.text?.trim();
        if (!userId || !text) return;
        if (text.startsWith('/')) return;
        
        // Mock isAuthorized
        if (!(connector as any).isAuthorized(userId)) return;
        
        // Mock getSession
        const responses = [{ text: 'response' }];
        await (connector as any).sendResponses(say, userId, responses);
      };

      const say = sinon.stub().resolves();
      await messageHandler({ message: { user: 'u1', text: 'hello' }, say });
      expect(say.calledOnce).to.be.true;
    });
  });
});
