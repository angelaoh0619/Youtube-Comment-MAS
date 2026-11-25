import {test,expect,type Page} from '@playwright/test';

const videoId='UF8uR6Z6KLc',analysisId='b'.repeat(32);
const example={analysis_id:'example',video_id:'BAHKmi4F1L8',is_example:true,title:'Could a shorter week work?',thumbnail_url:'/assets/videothumbnail.png',status:'ready',stage:'ready',detail:'Ready',collected_count:1217,agent_count:5,created_at:'',updated_at:''};
const newAnalysis={analysis_id:analysisId,video_id:videoId,is_example:false,title:'A different video topic',thumbnail_url:'/assets/videothumbnail.png',status:'running',stage:'collect',detail:'Collecting comments and replies',collected_count:24,agent_count:0,max_comments:200,created_at:'2026-11-25T00:00:00Z',updated_at:'2026-11-25T00:00:00Z'};
const perspectives=['g1','g2'].map((id,i)=>({agent_id:id,emoji:['🧭','🌱'][i],title:['Follow your own path','Keep learning and growing'][i],subtitle:'A perspective on this video',stance:'A position supported by the actual comments.',reasoning:'Commenters describe reasons for this view.',full_stance:'The full perspective.',statistics:{comment_count:10,comment_share:.5,like_count:5,like_share:.5},arguments:[],variations:[],limitations:[],representative_comments:[]}));

async function libraryApi(page:Page,{fail=false,interrupted=false,hosted=false}={}){
  let analyses:any[]=[example,...(interrupted?[{...newAnalysis,status:'interrupted',detail:'The server stopped. Resume this analysis.'}]:[])];
  let advance=false;
  const submissions:any[]=[],scopes:string[]=[];
  await page.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname,method=req.method(),body=method==='GET'?null:req.postDataJSON(),scope=req.headers()['x-analysis-id'];
    const reply=(data:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
    if(path==='/api/analyses'&&method==='POST'){
      submissions.push(body);
      if(body.url==='invalid')return reply({error:'Enter a valid YouTube video link.'},400);
      const record={...newAnalysis};analyses=[example,record];advance=!fail;return reply(record,202);
    }
    if(path===`/api/analyses/${analysisId}/retry`){analyses=[example,{...newAnalysis}];advance=true;return reply(newAnalysis,202);}
    if(path==='/api/analyses'){
      const response=structuredClone(analyses);
      if(analyses.length>1&&analyses[1].status==='running'){
        if(advance)analyses[1]={...newAnalysis,status:'ready',stage:'ready',detail:'Ready to explore',agent_count:2};
        else if(fail)analyses[1]={...newAnalysis,status:'failed',error:'Comments are disabled for this video.'};
      }
      return reply({analyses:response,can_analyze:!hosted});
    }
    if(path==='/api/bootstrap'){
      scopes.push(scope);
      const isExample=scope==='example';
      return reply({is_example:isExample,fingerprint:`library-${scope}`,video:{video_id:isExample?example.video_id:videoId,title:isExample?example.title:newAnalysis.title,url:`https://youtube.com/watch?v=${isExample?example.video_id:videoId}`},agents:isExample?perspectives.map(({emoji,...a})=>a):perspectives,counts:{collected:isExample?1217:24,keep:20,exclude:4,review:0,grouped:20,other:0,likes:10},other_statistics:{comment_count:0,comment_share:0,like_count:0,like_share:0},rooms:[]});
    }
    if(path==='/api/rooms')return reply([]);
    if(path==='/api/alignment')return reply({status:'completed',job_id:'alignment',result:{agents:[]}});
    if(path==='/api/compare')return reply({status:'completed',job_id:'compare',result:{similar:'A shared point.',different:'A difference.',consideration:'A question.',similar_quotes:[],different_quotes:[]}});
    return reply({error:'Unmocked endpoint '+path},404);
  });
  return {submissions,scopes};
}

test('home offers a new link and an immediate example without starting analysis',async({page})=>{
  const api=await libraryApi(page);await page.goto('/');
  await expect(page.getByRole('textbox',{name:'YouTube video link'})).toBeVisible();
  await expect(page.getByText('READY WHEN YOU ARE',{exact:true})).toHaveCount(0);
  await page.getByText('Analysis options',{exact:false}).click();
  await expect(page.getByLabel('Topic clarification',{exact:false})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Analyze video',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Explore example',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Your initial view',exact:true})).toBeVisible();
  expect(api.submissions).toHaveLength(0);expect(api.scopes).toContain('example');
  await page.getByRole('button',{name:'Choose a video',exact:true}).click();
  await expect(page.getByRole('button',{name:'Explore example',exact:true})).toBeVisible();
  await page.screenshot({path:'../screenshots/video-library-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.reload();
  await expect(page.getByRole('button',{name:'Explore example',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
  await expect(page.locator('.library-header')).toHaveCount(1);
  await page.screenshot({path:'../screenshots/video-library-mobile.png'});
  await page.getByRole('button',{name:'Explore example',exact:true}).scrollIntoViewIfNeeded();
  await page.screenshot({path:'../screenshots/video-library-mobile-example.png'});
});

test('new links show saved progress after reload and open an isolated workspace',async({page})=>{
  const api=await libraryApi(page);await page.goto('/');
  await page.getByRole('textbox',{name:'YouTube video link'}).fill(`https://youtu.be/${videoId}`);
  await page.getByText('Analysis options',{exact:false}).click();
  await page.getByLabel('Total comment limit').selectOption('200');
  await page.getByRole('button',{name:'Analyze video',exact:true}).click();
  await expect(page.getByRole('region',{name:'Video analysis progress'})).toContainText('24');
  await page.reload();
  await expect(page.getByRole('button',{name:'Explore this video',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Explore this video',exact:true}).click();
  await expect(page.getByRole('heading',{name:'A different video topic'})).toBeVisible();
  await page.getByRole('textbox',{name:'Your initial view',exact:true}).fill('My opinion on this new topic.');
  await page.getByRole('button',{name:'Save & explore perspectives'}).click();
  await expect(page.getByTestId('card-g1').locator('[data-emoji="🧭"]')).toBeVisible();
  await expect(page.getByTestId('card-g2').locator('[data-emoji="🌱"]')).toBeVisible();
  await page.getByTestId('card-g1').click();
  await expect(page.locator('.agent-modal-header [data-emoji="🧭"]')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.reload();
  await expect(page.getByTestId('card-g1').locator('[data-emoji="🧭"]')).toBeVisible();
  await page.getByRole('button',{name:'Choose a video',exact:true}).click();
  await page.getByRole('button',{name:'Explore example',exact:true}).click();
  await expect(page.getByRole('textbox',{name:'Your initial view',exact:true})).toHaveValue('');
  await page.getByRole('textbox',{name:'Your initial view',exact:true}).fill('A separate view for the example.');
  await page.getByRole('button',{name:'Save & explore perspectives'}).click();
  await expect(page.locator('.emoji-avatar')).toHaveCount(0);
  expect(api.submissions[0]).not.toHaveProperty('topic');
  expect(api.submissions[0]).toMatchObject({url:`https://youtu.be/${videoId}`,max_comments:200,with_replies:true,refresh:false});
  expect(api.scopes).toContain(analysisId);expect(api.scopes.at(-1)).toBe('example');
});

test('invalid links show actionable errors while the example stays available',async({page})=>{
  await libraryApi(page);await page.goto('/');
  await page.getByRole('textbox',{name:'YouTube video link'}).fill('invalid');
  await page.getByRole('button',{name:'Analyze video',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('valid YouTube');
  await expect(page.getByRole('button',{name:'Explore example',exact:true})).toBeEnabled();
});

test('failed and interrupted analyses can resume',async({page})=>{
  await libraryApi(page,{interrupted:true});
  await page.addInitScript(id=>localStorage.setItem('review:analysis-job',id),analysisId);
  await page.goto('/');await expect(page.getByRole('alert')).toContainText('server stopped');
  await page.getByRole('button',{name:'Resume analysis',exact:true}).click();
  await expect(page.getByRole('button',{name:'Explore this video',exact:true})).toBeVisible();
});

test('a collection failure is visible and can be retried',async({page})=>{
  await libraryApi(page,{fail:true});await page.goto('/');
  await page.getByRole('textbox',{name:'YouTube video link'}).fill(`https://youtu.be/${videoId}`);
  await page.getByRole('button',{name:'Analyze video',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Comments are disabled');
  await page.getByRole('button',{name:'Resume analysis',exact:true}).click();
  await expect(page.getByRole('button',{name:'Explore this video',exact:true})).toBeVisible();
});

test('hosted example remains available with local analysis explained',async({page})=>{
  await libraryApi(page,{hosted:true});await page.goto('/');
  await expect(page.getByRole('button',{name:'Analyze video',exact:true})).toBeDisabled();
  await expect(page.getByText('New video analysis is available in the local app.',{exact:false})).toBeVisible();
  await expect(page.getByRole('button',{name:'Explore example',exact:true})).toBeEnabled();
});
